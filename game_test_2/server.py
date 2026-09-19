# server.py
import asyncio
import random
import socket
from typing import Dict, Optional
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from game_state import GameEngine, Phase, Role, PlayerState
from protocol import Packet, MessageType, make_error_packet, make_system_packet, make_chat_packet

console = Console()

HOST = "0.0.0.0"
PORT = 8888
NIGHT_DURATION = 20
DAY_DISCUSSION_DURATION = 20
VOTING_DURATION = 20


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


class ClientConnection:
    def __init__(self, player_id: int, writer: asyncio.StreamWriter):
        self.player_id = player_id
        self.writer = writer


class MafiaServerHost:
    def __init__(self):
        self.engine = GameEngine(min_players=4)
        self.connections: Dict[int, ClientConnection] = {}
        self.skip_phase_event = asyncio.Event()

    async def send_packet(self, writer: asyncio.StreamWriter, packet: Packet):
        try:
            writer.write(packet.encode())
            await writer.drain()
        except Exception:
            pass

    async def broadcast(self, packet: Packet, active_only: bool = False):
        for pid, conn in list(self.connections.items()):
            player = self.engine.players.get(pid)
            if active_only and player and not player.in_active_game:
                continue
            await self.send_packet(conn.writer, packet)

    async def broadcast_player_list(self):
        plist = [p.to_dict() for p in self.engine.players.values()]
        await self.broadcast(Packet(type=MessageType.PLAYER_LIST, players=plist))

    async def handle_disconnect(self, player_id: int):
        conn = self.connections.pop(player_id, None)
        if conn:
            try:
                conn.writer.close()
                await conn.writer.wait_closed()
            except Exception:
                pass

        player = self.engine.remove_player(player_id)
        if player:
            console.print(f"[bold red][DISCONNECT][/bold red] '{player.name}' left.")
            await self.broadcast(make_system_packet(f"⚠️ {player.name} left the room."))
            await self.broadcast_player_list()

            if self.engine.is_game_running:
                await self.check_and_process_win()

    async def client_listener(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
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

            player = self.engine.add_player(name)
            player_id = player.id
            self.connections[player_id] = ClientConnection(player_id, writer)

            console.print(f"[bold green][JOIN][/bold green] '{player.name}' (ID: {player_id}) connected.")

            # Welcome packet
            await self.send_packet(writer, Packet(
                type=MessageType.WELCOME,
                player_id=player.id,
                message=f"Welcome to Mafia CLI, {player.name}!"
            ))

            if self.engine.is_game_running:
                await self.send_packet(writer, Packet(
                    type=MessageType.LOBBY_WAIT,
                    message="⏳ A game is currently in progress. You are placed in the spectator lobby."
                ))
            else:
                await self.broadcast(make_system_packet(f"🎮 {player.name} joined the lobby!"))

            await self.broadcast_player_list()

            while True:
                line = await reader.readline()
                if not line:
                    break

                try:
                    packet = Packet.decode(line)
                    await self.process_client_packet(player_id, packet)
                except ValidationError:
                    await self.send_packet(writer, make_error_packet("Invalid command payload."))

        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            pass
        finally:
            if player_id:
                await self.handle_disconnect(player_id)

    async def process_client_packet(self, player_id: int, packet: Packet):
        player = self.engine.players.get(player_id)
        if not player:
            return

        conn = self.connections.get(player_id)

        if packet.type == MessageType.CHAT:
            if player.is_alive or not self.engine.is_game_running:
                await self.broadcast(make_chat_packet(player.name, packet.text or ""))
            else:
                # Dead chat
                dead_pids = [p.id for p in self.engine.players.values() if not p.is_alive]
                for dpid in dead_pids:
                    c = self.connections.get(dpid)
                    if c:
                        await self.send_packet(c.writer, make_chat_packet(f"[GHOST] {player.name}", packet.text or ""))

        elif packet.type == MessageType.NIGHT_ACTION:
            if self.engine.current_phase == Phase.NIGHT and player.is_alive and player.in_active_game:
                player.night_action = packet.target_id
                if conn:
                    await self.send_packet(conn.writer, make_system_packet("Target selection saved."))

        elif packet.type == MessageType.VOTE:
            if self.engine.current_phase == Phase.DAY_VOTING and player.is_alive and player.in_active_game:
                player.vote = packet.target_id
                if conn:
                    await self.send_packet(conn.writer, make_system_packet("Vote submitted."))

        elif packet.type == MessageType.LEAVE_TO_LOBBY:
            player.in_active_game = False
            player.is_alive = False
            await self.broadcast(make_system_packet(f"🚪 {player.name} returned to the spectator lobby."))
            if conn:
                await self.send_packet(conn.writer, Packet(
                    type=MessageType.LOBBY_WAIT,
                    message="You returned to the spectator lobby."
                ))
            await self.broadcast_player_list()
            await self.check_and_process_win()

    async def run_game_loop(self):
        console.print(Panel("[bold green]Starting Match...[/bold green]"))
        
        # Notify active game players
        for p in self.engine.get_active_players():
            conn = self.connections.get(p.id)
            if conn:
                teammates = [m.name for m in self.engine.get_active_players() if m.role == Role.MAFIA and m.id != p.id]
                await self.send_packet(conn.writer, Packet(
                    type=MessageType.ROLE_ASSIGNMENT,
                    role=p.role.value,
                    mafia_teammates=teammates if p.role == Role.MAFIA else []
                ))

        await self.broadcast(make_system_packet("🎭 Game starting! Roles assigned."))
        await asyncio.sleep(2)

        while self.engine.is_game_running and self.engine.current_phase != Phase.GAME_OVER:
            # --- NIGHT PHASE ---
            self.engine.current_phase = Phase.NIGHT
            await self.broadcast_player_list()
            await self.broadcast(Packet(
                type=MessageType.PHASE_CHANGE,
                phase=Phase.NIGHT.value,
                duration=NIGHT_DURATION,
                message="🌙 Night falls. Active special roles perform actions."
            ))
            
            await self.bot_night_actions()
            await self.wait_phase(NIGHT_DURATION)

            death_msg, inv_result = self.engine.resolve_night()

            if inv_result:
                det_conn = self.connections.get(inv_result["detective_id"])
                if det_conn:
                    txt = f"🔍 {inv_result['target_name']} is {'MAFIA' if inv_result['is_mafia'] else 'NOT Mafia'}."
                    await self.send_packet(det_conn.writer, Packet(type=MessageType.INVESTIGATION_RESULT, message=txt))

            await self.broadcast(Packet(type=MessageType.NIGHT_RESULT, message=death_msg))

            if await self.check_and_process_win():
                break

            # --- DAY DISCUSSION ---
            self.engine.current_phase = Phase.DAY_DISCUSSION
            await self.broadcast_player_list()
            await self.broadcast(Packet(
                type=MessageType.PHASE_CHANGE,
                phase=Phase.DAY_DISCUSSION.value,
                duration=DAY_DISCUSSION_DURATION,
                message="☀️ Sun rises! Discuss and debate who the Mafia is."
            ))
            await self.wait_phase(DAY_DISCUSSION_DURATION)

            # --- DAY VOTING ---
            self.engine.current_phase = Phase.DAY_VOTING
            await self.broadcast(Packet(
                type=MessageType.PHASE_CHANGE,
                phase=Phase.DAY_VOTING.value,
                duration=VOTING_DURATION,
                message="⚖️ Voting Phase! Select a player to eliminate."
            ))
            await self.bot_voting_actions()
            await self.wait_phase(VOTING_DURATION)

            elim_msg = self.engine.resolve_voting()
            await self.broadcast(Packet(type=MessageType.ELIMINATION, message=elim_msg))

            if await self.check_and_process_win():
                break

    async def wait_phase(self, duration: int):
        """Sleeps for duration or until server host triggers 'next'."""
        self.skip_phase_event.clear()
        try:
            await asyncio.wait_for(self.skip_phase_event.wait(), timeout=duration)
            console.print("[bold yellow][SERVER][/bold yellow] Phase force-advanced by host operator.")
        except asyncio.TimeoutError:
            pass

    async def bot_night_actions(self):
        for b in [p for p in self.engine.get_alive_players() if p.is_bot]:
            await asyncio.sleep(random.uniform(0.5, 1.5))
            alive = [p.id for p in self.engine.get_alive_players() if p.id != b.id]
            if alive:
                b.night_action = random.choice(alive)

    async def bot_voting_actions(self):
        for b in [p for p in self.engine.get_alive_players() if p.is_bot]:
            await asyncio.sleep(random.uniform(0.5, 1.5))
            alive = [p.id for p in self.engine.get_alive_players() if p.id != b.id]
            if alive:
                b.vote = random.choice(alive)

    async def check_and_process_win(self) -> bool:
        winner = self.engine.check_win_condition()
        if winner:
            self.engine.current_phase = Phase.GAME_OVER
            summary = {p.name: p.role.value for p in self.engine.get_active_players()}
            await self.broadcast(Packet(
                type=MessageType.GAME_OVER,
                winner=winner,
                role_summary=summary
            ))
            self.engine.reset_to_lobby()
            await self.broadcast(make_system_packet("🔄 Match ended. All players returned to the active lobby."))
            await self.broadcast_player_list()
            return True
        return False

    async def server_operator_console(self):
        """Interactive Server Host Command Menu."""
        loop = asyncio.get_running_loop()
        while True:
            cmd = await loop.run_in_executor(None, input, "SERVER-HOST> ")
            cmd = cmd.strip().lower()

            if not cmd:
                continue

            if cmd == "start":
                if self.engine.is_game_running:
                    console.print("[bold red]Game already in progress![/bold red]")
                else:
                    success = self.engine.start_game()
                    if success:
                        asyncio.create_task(self.run_game_loop())
                    else:
                        console.print(f"[bold red]Need at least {self.engine.min_players} players in lobby.[/bold red]")

            elif cmd == "next":
                if self.engine.is_game_running:
                    self.skip_phase_event.set()
                else:
                    console.print("[bold red]No active game to advance.[/bold red]")

            elif cmd == "reset":
                self.engine.reset_to_lobby()
                self.skip_phase_event.set()
                await self.broadcast(make_system_packet("⚠️ Game force-reset by Server Operator."))
                await self.broadcast_player_list()
                console.print("[bold yellow]Game state reset to Lobby.[/bold yellow]")

            elif cmd == "bot":
                bot = self.engine.add_player(f"Bot_{random.randint(10, 99)}", is_bot=True)
                console.print(f"[bold green]Added AI Bot: {bot.name}[/bold green]")
                await self.broadcast(make_system_packet(f"🤖 AI Bot '{bot.name}' added."))
                await self.broadcast_player_list()

            elif cmd.startswith("kick "):
                try:
                    target_id = int(cmd.split()[1])
                    conn = self.connections.get(target_id)
                    if conn:
                        await self.send_packet(conn.writer, Packet(type=MessageType.KICKED, message="You were kicked by the server host."))
                        await self.handle_disconnect(target_id)
                        console.print(f"[yellow]Kicked Player ID {target_id}.[/yellow]")
                    else:
                        console.print("[red]Player ID not found.[/red]")
                except ValueError:
                    console.print("[red]Usage: kick <player_id>[/red]")

            elif cmd == "status":
                table = Table(title="SERVER OPERATOR MONITOR")
                table.add_column("ID", justify="center")
                table.add_column("Name")
                table.add_column("Type")
                table.add_column("Status")
                table.add_column("In Game?")

                for p in self.engine.players.values():
                    ptype = "AI BOT" if p.is_bot else "HUMAN"
                    st = "[green]ALIVE[/green]" if p.is_alive else "[red]DEAD[/red]"
                    ingame = "YES" if p.in_active_game else "NO (Lobby Queue)"
                    table.add_row(str(p.id), p.name, ptype, st, ingame)

                console.print(table)
                console.print(f"[bold]Game Running:[/bold] {self.engine.is_game_running} | [bold]Phase:[/bold] {self.engine.current_phase}")

            elif cmd == "help":
                console.print("""
[bold cyan]Available Host Commands:[/bold cyan]
  start      - Start a new game using lobby players
  next       - Advance the current game phase timer immediately
  reset      - Force reset current game back to lobby
  bot        - Add an AI Bot to fill lobby slots
  kick <id>  - Kick a player by ID
  status     - Show detailed player directory and phase status
  help       - Show this command list
""")
            else:
                console.print("[dim]Unknown host command. Type 'help' for options.[/dim]")


async def main():
    host_server = MafiaServerHost()
    local_ip = get_local_ip()

    server = await asyncio.start_server(host_server.client_listener, HOST, PORT)

    console.print(Panel(f"""[bold green]MAFIA CLI SERVER IS LIVE![/bold green]
👉 LAN IP:   [bold yellow]{local_ip}[/bold yellow]
👉 PORT:     [bold yellow]{PORT}[/bold yellow]
👉 HOST CLI: Type '[bold cyan]help[/bold cyan]' for operator control commands.""", title="SERVER OPERATOR CONSOLE"))

    async with server:
        await asyncio.gather(
            server.serve_forever(),
            host_server.server_operator_console()
        )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Server shut down by user.[/yellow]")