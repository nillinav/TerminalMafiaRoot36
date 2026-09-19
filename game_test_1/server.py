# server.py
import asyncio
import socket
from pydantic import ValidationError
from game_state import GameState, Phase, Role
from protocol import Packet, MessageType, make_error_packet, make_system_packet, make_chat_packet

HOST = "0.0.0.0"
PORT = 8888
NIGHT_DURATION_SEC = 15
DAY_DISCUSSION_SEC = 15
VOTING_DURATION_SEC = 15

def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


class ConnectedClient:
    def __init__(self, player_id: int, writer: asyncio.StreamWriter):
        self.player_id = player_id
        self.writer = writer


class MafiaServer:
    def __init__(self):
        self.game = GameState(min_players=4)
        self.clients = {}  # {player_id: ConnectedClient}

    async def send_packet(self, writer: asyncio.StreamWriter, packet: Packet):
        try:
            writer.write(packet.encode())
            await writer.drain()
        except Exception:
            pass

    async def broadcast(self, packet: Packet):
        for client in list(self.clients.values()):
            await self.send_packet(client.writer, packet)

    async def broadcast_player_list(self):
        plist = [p.to_dict() for p in self.game.players.values()]
        await self.broadcast(Packet(type=MessageType.PLAYER_LIST, players=plist))

    async def handle_disconnect(self, player_id: int):
        if player_id in self.clients:
            del self.clients[player_id]
        player = self.game.remove_player(player_id)
        if player:
            print(f"[DISCONNECT] {player.name} (ID: {player_id}) left.")
            await self.broadcast(make_system_packet(f"⚠️ {player.name} left the game."))
            await self.broadcast_player_list()
            
            if self.game.current_phase != Phase.LOBBY:
                await self.check_and_process_win()

    async def client_handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        player_id = None
        try:
            line = await reader.readline()
            if not line:
                return

            try:
                handshake = Packet.decode(line)
                name = handshake.name or "Player"
            except ValidationError:
                await self.send_packet(writer, make_error_packet("Invalid Handshake."))
                return

            player = self.game.add_player(name)
            player_id = player.id
            self.clients[player_id] = ConnectedClient(player_id, writer)

            print(f"[JOIN] '{player.name}' joined from {writer.get_extra_info('peername')}")

            await self.send_packet(writer, Packet(
                type=MessageType.WELCOME,
                player_id=player.id,
                is_host=(player.id == self.game.host_id),
                message=f"Welcome to Mafia CLI, {player.name}!"
            ))

            await self.broadcast(make_system_packet(f"🎮 {player.name} joined! ({len(self.game.players)} in lobby)"))
            await self.broadcast_player_list()

            while True:
                line = await reader.readline()
                if not line:
                    break

                try:
                    packet = Packet.decode(line)
                    await self.process_packet(player_id, packet)
                except ValidationError:
                    await self.send_packet(writer, make_error_packet("Invalid command format."))

        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            if player_id:
                await self.handle_disconnect(player_id)

    async def process_packet(self, player_id: int, packet: Packet):
        player = self.game.players.get(player_id)
        if not player:
            return

        if packet.type == MessageType.CHAT:
            if player.is_alive or self.game.current_phase == Phase.LOBBY:
                await self.broadcast(make_chat_packet(player.name, packet.text or ""))

        elif packet.type == MessageType.START_GAME:
            if player_id != self.game.host_id:
                client = self.clients.get(player_id)
                if client:
                    await self.send_packet(client.writer, make_error_packet("Only the host can start."))
            elif len(self.game.players) < self.game.min_players:
                client = self.clients.get(player_id)
                if client:
                    await self.send_packet(client.writer, make_error_packet(f"Need {self.game.min_players}+ players."))
            elif self.game.current_phase == Phase.LOBBY:
                asyncio.create_task(self.run_game_loop())

        elif packet.type == MessageType.NIGHT_ACTION:
            if self.game.current_phase == Phase.NIGHT and player.is_alive:
                player.night_action = packet.target_id
                client = self.clients.get(player_id)
                if client:
                    await self.send_packet(client.writer, make_system_packet("Night action saved."))

        elif packet.type == MessageType.VOTE:
            if self.game.current_phase == Phase.DAY_VOTING and player.is_alive:
                player.vote = packet.target_id
                client = self.clients.get(player_id)
                if client:
                    await self.send_packet(client.writer, make_system_packet("Vote recorded."))

    async def run_game_loop(self):
        print("[GAME] Match starting...")
        self.game.assign_roles()

        for p in self.game.players.values():
            client = self.clients.get(p.id)
            if client:
                teammates = [m.name for m in self.game.players.values() if m.role == Role.MAFIA and m.id != p.id]
                await self.send_packet(client.writer, Packet(
                    type=MessageType.ROLE_ASSIGNMENT,
                    role=p.role.value,
                    mafia_teammates=teammates if p.role == Role.MAFIA else []
                ))

        await self.broadcast(make_system_packet("🎭 Roles assigned! Read your secret screen."))
        await asyncio.sleep(3)

        while self.game.current_phase != Phase.GAME_OVER:
            # NIGHT PHASE
            self.game.current_phase = Phase.NIGHT
            await self.broadcast_player_list()
            await self.broadcast(Packet(
                type=MessageType.PHASE_CHANGE,
                phase=Phase.NIGHT.value,
                duration=NIGHT_DURATION_SEC,
                message="🌙 Night falls. Active roles perform your secret actions!"
            ))
            await asyncio.sleep(NIGHT_DURATION_SEC)

            death_msg, inv_result = self.game.resolve_night()
            
            if inv_result:
                det_client = self.clients.get(inv_result["detective_id"])
                if det_client:
                    res_text = f"🔍 {inv_result['target_name']} is {'MAFIA' if inv_result['is_mafia'] else 'NOT Mafia'}."
                    await self.send_packet(det_client.writer, Packet(type=MessageType.INVESTIGATION_RESULT, message=res_text))

            await self.broadcast(Packet(type=MessageType.NIGHT_RESULT, message=death_msg))

            if await self.check_and_process_win():
                break

            # DAY DISCUSSION
            self.game.current_phase = Phase.DAY_DISCUSSION
            await self.broadcast_player_list()
            await self.broadcast(Packet(
                type=MessageType.PHASE_CHANGE,
                phase=Phase.DAY_DISCUSSION.value,
                duration=DAY_DISCUSSION_SEC,
                message="☀️ Sun rises! Discuss and uncover the suspects."
            ))
            await asyncio.sleep(DAY_DISCUSSION_SEC)

            # DAY VOTING
            self.game.current_phase = Phase.DAY_VOTING
            await self.broadcast(Packet(
                type=MessageType.PHASE_CHANGE,
                phase=Phase.DAY_VOTING.value,
                duration=VOTING_DURATION_SEC,
                message="⚖️ Voting time! Cast your vote using '/vote <id>'."
            ))
            await asyncio.sleep(VOTING_DURATION_SEC)

            elim_msg = self.game.resolve_voting()
            await self.broadcast(Packet(type=MessageType.ELIMINATION, message=elim_msg))

            if await self.check_and_process_win():
                break

    async def check_and_process_win(self) -> bool:
        winner = self.game.check_win_condition()
        if winner:
            self.game.current_phase = Phase.GAME_OVER
            summary = {p.name: p.role.value for p in self.game.players.values()}
            await self.broadcast(Packet(
                type=MessageType.GAME_OVER,
                winner=winner,
                role_summary=summary
            ))
            return True
        return False


async def main():
    local_ip = get_local_ip()
    server_instance = MafiaServer()

    server = await asyncio.start_server(server_instance.client_handler, HOST, PORT)

    print("=" * 60)
    print(f"  MAFIA CLI SERVER RUNNING")
    print(f"  Join IP:   {local_ip}")
    print(f"  Port:      {PORT}")
    print("=" * 60)

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer closed.")