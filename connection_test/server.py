import asyncio
import json
import random
import socket
import sys

# Game Configuration
HOST = "0.0.0.0"
PORT = 8888
MIN_PLAYERS = 4
NIGHT_DURATION_SEC = 20
DAY_DISCUSSION_SEC = 20
VOTING_DURATION_SEC = 20

def get_local_ip():
    """Finds the local IP address of this host machine for players to connect."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

class Player:
    def __init__(self, player_id: int, name: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.id = player_id
        self.name = name
        self.reader = reader
        self.writer = writer
        self.role = "Villager"
        self.is_alive = True
        self.night_action = None  # Holds player_id target for night
        self.vote = None          # Holds player_id target for day voting

class GameServer:
    def __init__(self):
        self.players = {}  # {player_id: Player}
        self.next_player_id = 1
        self.game_state = "LOBBY"  # LOBBY, NIGHT, DAY_DISCUSSION, DAY_VOTING, GAME_OVER"
        self.host_id = None

    async def send_to_player(self, player: Player, data: dict):
        """Sends a JSON message to a single player."""
        try:
            message = json.dumps(data) + "\n"
            player.writer.write(message.encode())
            await player.writer.drain()
        except Exception:
            await self.handle_disconnect(player)

    async def broadcast(self, data: dict, alive_only: bool = False):
        """Sends a JSON message to all connected players."""
        for player in list(self.players.values()):
            if alive_only and not player.is_alive:
                continue
            await self.send_to_player(player, data)

    async def handle_disconnect(self, player: Player):
        """Handles player disconnection gracefully."""
        if player.id in self.players:
            print(f"[DISCONNECT] Player '{player.name}' (ID: {player.id}) disconnected.")
            del self.players[player.id]
            
            # Notify remaining players
            await self.broadcast({
                "type": "SYSTEM",
                "message": f"⚠️ Player {player.name} disconnected!"
            })

            # Check if win conditions are met if game is currently running
            if self.game_state not in ["LOBBY", "GAME_OVER"]:
                await self.check_win_conditions()

    async def client_handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Listens for network messages from an individual player."""
        player = None
        try:
            # Step 1: Initial Handshake / Registration
            data = await reader.readline()
            if not data:
                return
            
            payload = json.loads(data.decode().strip())
            player_name = payload.get("name", f"Player_{self.next_player_id}")
            
            # Initialize Player
            player_id = self.next_player_id
            self.next_player_id += 1
            player = Player(player_id, player_name, reader, writer)
            self.players[player_id] = player

            if len(self.players) == 1:
                self.host_id = player_id

            print(f"[JOIN] '{player.name}' connected from {writer.get_extra_info('peername')}")

            # Send welcome info to client
            await self.send_to_player(player, {
                "type": "WELCOME",
                "player_id": player.id,
                "is_host": (player.id == self.host_id),
                "message": f"Welcome to Mafia CLI, {player.name}!"
            })

            # Notify everyone in room
            await self.broadcast({
                "type": "SYSTEM",
                "message": f"🎮 {player.name} joined the game! ({len(self.players)} connected)"
            })

            # Step 2: Continuous Message Listening Loop
            while True:
                line = await reader.readline()
                if not line:
                    break
                
                try:
                    msg = json.loads(line.decode().strip())
                    await self.process_player_message(player, msg)
                except json.JSONDecodeError:
                    await self.send_to_player(player, {"type": "ERROR", "message": "Invalid JSON payload."})

        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            if player:
                await self.handle_disconnect(player)

    async def process_player_message(self, player: Player, msg: dict):
        """Processes typed events from clients."""
        msg_type = msg.get("type")

        # Chat message
        if msg_type == "CHAT":
            text = msg.get("text", "")
            if player.is_alive or self.game_state == "LOBBY":
                await self.broadcast({
                    "type": "CHAT",
                    "sender": player.name,
                    "text": text
                })
            else:
                # Dead players can only chat with other dead players
                dead_players = [p for p in self.players.values() if not p.is_alive]
                for dp in dead_players:
                    await self.send_to_player(dp, {
                        "type": "CHAT",
                        "sender": f"[GHOST] {player.name}",
                        "text": text
                    })

        # Start game command (Host only)
        elif msg_type == "START_GAME":
            if player.id != self.host_id:
                await self.send_to_player(player, {"type": "ERROR", "message": "Only the host can start the game."})
            elif len(self.players) < MIN_PLAYERS:
                await self.send_to_player(player, {"type": "ERROR", "message": f"Need at least {MIN_PLAYERS} players to start."})
            elif self.game_state == "LOBBY":
                asyncio.create_task(self.run_game_loop())

        # Night Phase Action
        elif msg_type == "NIGHT_ACTION":
            if self.game_state == "NIGHT" and player.is_alive:
                target_id = msg.get("target_id")
                player.night_action = target_id
                await self.send_to_player(player, {"type": "SYSTEM", "message": "Action recorded."})

        # Voting Phase Action
        elif msg_type == "VOTE":
            if self.game_state == "DAY_VOTING" and player.is_alive:
                target_id = msg.get("target_id")
                player.vote = target_id
                await self.send_to_player(player, {"type": "SYSTEM", "message": "Vote submitted."})

    # =========================================================================
    # CORE GAME LOOP & STATE MACHINE
    # =========================================================================

    async def run_game_loop(self):
        """Executes the complete Mafia state machine."""
        print("[GAME] Starting match...")
        self.assign_roles()
        
        # Broadcast Secret Roles to each player
        for p in self.players.values():
            teammates = [m.name for m in self.players.values() if m.role == "Mafia" and m.id != p.id]
            await self.send_to_player(p, {
                "type": "ROLE_ASSIGNMENT",
                "role": p.role,
                "mafia_teammates": teammates if p.role == "Mafia" else []
            })

        await self.broadcast({"type": "SYSTEM", "message": "🎭 Game Starting! Check your secret roles."})
        await asyncio.sleep(3)

        # Main Loop (Night -> Day -> Vote)
        while self.game_state != "GAME_OVER":
            # --- 1. NIGHT PHASE ---
            self.game_state = "NIGHT"
            await self.broadcast_player_list()
            await self.broadcast({
                "type": "PHASE_CHANGE",
                "phase": "NIGHT",
                "duration": NIGHT_DURATION_SEC,
                "message": "🌙 Night has fallen. Special roles, choose your targets!"
            })
            
            # Reset actions
            for p in self.players.values():
                p.night_action = None

            await asyncio.sleep(NIGHT_DURATION_SEC)
            await self.resolve_night_phase()

            if await self.check_win_conditions():
                break

            # --- 2. DAY DISCUSSION PHASE ---
            self.game_state = "DAY_DISCUSSION"
            await self.broadcast_player_list()
            await self.broadcast({
                "type": "PHASE_CHANGE",
                "phase": "DAY_DISCUSSION",
                "duration": DAY_DISCUSSION_SEC,
                "message": "☀️ Day breaks! Discuss who you suspect is the Mafia."
            })
            
            await asyncio.sleep(DAY_DISCUSSION_SEC)

            # --- 3. DAY VOTING PHASE ---
            self.game_state = "DAY_VOTING"
            for p in self.players.values():
                p.vote = None

            await self.broadcast({
                "type": "PHASE_CHANGE",
                "phase": "DAY_VOTING",
                "duration": VOTING_DURATION_SEC,
                "message": "⚖️ Voting phase! Submit your vote for who to eliminate."
            })

            await asyncio.sleep(VOTING_DURATION_SEC)
            await self.resolve_voting_phase()

            if await self.check_win_conditions():
                break

    def assign_roles(self):
        """Assigns roles dynamically based on total player count."""
        player_list = list(self.players.values())
        random.shuffle(player_list)

        num_players = len(player_list)
        num_mafia = max(1, num_players // 4)

        # Assign Roles
        for i, player in enumerate(player_list):
            if i < num_mafia:
                player.role = "Mafia"
            elif i == num_mafia:
                player.role = "Doctor"
            elif i == num_mafia + 1:
                player.role = "Detective"
            else:
                player.role = "Villager"

    async def resolve_night_phase(self):
        """Processes Mafia kills, Doctor saves, and Detective investigations."""
        mafia_targets = []
        doctor_save_id = None
        detective_investigate_id = None

        for p in self.players.values():
            if not p.is_alive:
                continue
            if p.role == "Mafia" and p.night_action:
                mafia_targets.append(p.night_action)
            elif p.role == "Doctor":
                doctor_save_id = p.night_action
            elif p.role == "Detective":
                detective_investigate_id = p.night_action

        # Determine Mafia Victim (Majority vote or random tiebreak)
        victim_id = None
        if mafia_targets:
            victim_id = max(set(mafia_targets), key=mafia_targets.count)

        # Handle Detective Secret Feedback
        if detective_investigate_id and detective_investigate_id in self.players:
            target = self.players[detective_investigate_id]
            is_mafia = (target.role == "Mafia")
            det_player = next((p for p in self.players.values() if p.role == "Detective"), None)
            if det_player:
                await self.send_to_player(det_player, {
                    "type": "INVESTIGATION_RESULT",
                    "target_name": target.name,
                    "is_mafia": is_mafia,
                    "message": f"🔍 Investigation Result: {target.name} is {'MAFIA' if is_mafia else 'NOT Mafia'}."
                })

        # Process Death / Save
        if victim_id and victim_id in self.players:
            victim = self.players[victim_id]
            if victim_id == doctor_save_id:
                await self.broadcast({
                    "type": "SYSTEM",
                    "message": "🛡️ Someone was attacked during the night, but was saved by the Doctor!"
                })
            else:
                victim.is_alive = False
                await self.broadcast({
                    "type": "NIGHT_RESULT",
                    "message": f"☠️ {victim.name} was killed in the night! Their role was {victim.role}."
                })
        else:
            await self.broadcast({
                "type": "SYSTEM",
                "message": "🌅 The night was peaceful. No one died."
            })

    async def resolve_voting_phase(self):
        """Tallies votes and eliminates the top target."""
        votes = {} # {target_id: count}
        for p in self.players.values():
            if p.is_alive and p.vote in self.players:
                votes[p.vote] = votes.get(p.vote, 0) + 1

        if not votes:
            await self.broadcast({"type": "SYSTEM", "message": "🗳️ No votes were cast. Nobody was eliminated."})
            return

        # Find top target
        max_votes = max(votes.values())
        top_targets = [target_id for target_id, count in votes.items() if count == max_votes]

        if len(top_targets) > 1:
            await self.broadcast({"type": "SYSTEM", "message": "⚖️ Tie vote! No one was eliminated today."})
        else:
            eliminated_id = top_targets[0]
            eliminated = self.players[eliminated_id]
            eliminated.is_alive = False
            await self.broadcast({
                "type": "ELIMINATION",
                "message": f"💀 {eliminated.name} was voted out! They were a {eliminated.role}."
            })

    async def check_win_conditions(self) -> bool:
        """Checks if Mafia or Villagers have won the game."""
        alive_mafia = [p for p in self.players.values() if p.is_alive and p.role == "Mafia"]
        alive_town = [p for p in self.players.values() if p.is_alive and p.role != "Mafia"]

        winner = None
        if len(alive_mafia) == 0:
            winner = "VILLAGERS"
        elif len(alive_mafia) >= len(alive_town):
            winner = "MAFIA"

        if winner:
            self.game_state = "GAME_OVER"
            # Reveal all remaining roles
            role_summary = {p.name: p.role for p in self.players.values()}
            await self.broadcast({
                "type": "GAME_OVER",
                "winner": winner,
                "role_summary": role_summary,
                "message": f"🎉 GAME OVER! The {winner} HAVE WON!"
            })
            return True
        return False

    async def broadcast_player_list(self):
        """Sends updated list of alive/dead players to all clients."""
        plist = [
            {"id": p.id, "name": p.name, "is_alive": p.is_alive}
            for p in self.players.values()
        ]
        await self.broadcast({"type": "PLAYER_LIST", "players": plist})


async def main():
    local_ip = get_local_ip()
    game_server = GameServer()

    server = await asyncio.start_server(game_server.client_handler, HOST, PORT)

    print("=" * 60)
    print(f"  MAFIA CLI GAME SERVER IS LIVE!")
    print(f"  Connect players locally on your LAN to:")
    print(f"  👉  IP:   {local_ip}")
    print(f"  👉  PORT: {PORT}")
    print("=" * 60)

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer shut down manually.")