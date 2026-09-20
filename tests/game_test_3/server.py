import asyncio
import json
import sys
import random
from typing import Dict, List, Optional

from rich.console import Console
from rich.table import Table

import botai
from game_state import GameEngine, Phase, Role
from protocol import Packet, MessageType, make_system_packet, make_chat_packet

console = Console()

DAY_DISCUSSION_DURATION = 45
DAY_VOTING_DURATION = 45
NIGHT_DURATION = 45

# ==========================================
# AUDIO PLACEHOLDER SYSTEM
# ==========================================
def play_sound(effect_name: str):
    """Placeholder for sound effects."""
    print(f"[AUDIO] Playing sound: {effect_name}.wav")

# ==========================================
# SERVER CLASS
# ==========================================
class MafiaServer:
    def __init__(self):
        # Rely on game_state.py for the underlying rules and player state
        self.engine = GameEngine(min_players=4)
        
        # Track active socket connections for human players
        self.connections: Dict[int, asyncio.StreamWriter] = {}
        
        # Async event to allow the host to skip phase timers
        self.skip_phase_event = asyncio.Event()
        
        self.day_counter = 0
        self.voting_history: Dict[int, List[str]] = {}

    # --- NETWORK & UTILITY METHODS ---
    async def broadcast(self, packet: Packet):
        """Sends a protocol Packet to all connected human players."""
        data = packet.encode()
        for writer in self.connections.values():
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                pass

    async def send_packet(self, writer: asyncio.StreamWriter, packet: Packet):
        """Sends a protocol Packet to a specific client."""
        try:
            writer.write(packet.encode())
            await writer.drain()
        except Exception:
            pass

    async def broadcast_player_list(self):
        """Broadcasts the current state of all players to all clients."""
        players_data = [p.to_dict() for p in self.engine.players.values()]
        await self.broadcast(Packet(type=MessageType.PLAYER_LIST, players=players_data))

    async def handle_disconnect(self, target_id: int):
        """Safely cleans up network and engine state for a disconnected player."""
        writer = self.connections.pop(target_id, None)
        if writer:
            writer.close()
            await writer.wait_closed()
            
        player = self.engine.remove_player(target_id)
        if player:
            await self.broadcast(make_system_packet(f"❌ {player.name} disconnected."))
            await self.broadcast_player_list()

    async def wait_phase(self, duration: int):
        """Sleeps for the phase duration unless interrupted by the skip_phase_event."""
        try:
            await asyncio.wait_for(self.skip_phase_event.wait(), timeout=duration)
        except asyncio.TimeoutError:
            pass # Timeout naturally reached
        finally:
            self.skip_phase_event.clear() # Reset event for the next phase

    # --- BOT BEHAVIOR ROUTINES ---
    async def trigger_bot_routines(self, duration: int):
        """Schedules timed bot chats and mechanical actions using botai."""
        alive_bots = {
            p.id: {"name": p.name, "role": p.role.value if p.role else "Villager"} 
            for p in self.engine.get_alive_players() if p.is_bot
        }
        if not alive_bots:
            return

        current_phase = self.engine.current_phase

        # 1. Generate Chats
        chats = await botai.generate_bot_responses(alive_bots, current_phase.value, duration)
        
        async def delayed_chat(bot_id, text, delay):
            await asyncio.sleep(delay)
            # Ensure game state is still valid
            if self.engine.current_phase == current_phase and bot_id in self.engine.players and self.engine.players[bot_id].is_alive:
                bot = self.engine.players[bot_id]
                await self.broadcast(make_chat_packet(bot.name, text))

        for chat in chats:
            asyncio.create_task(delayed_chat(chat["id"], chat["text"], chat["delay"]))

        # 2. Generate Mechanical Actions
        if current_phase in [Phase.DAY_VOTING, Phase.NIGHT]:
            async def delayed_action(bot_id, delay):
                await asyncio.sleep(delay)
                
                if self.engine.current_phase != current_phase or bot_id not in self.engine.players or not self.engine.players[bot_id].is_alive:
                    return
                
                bot = self.engine.players[bot_id]
                alive_ids = [p.id for p in self.engine.get_alive_players() if p.id != bot.id]
                
                target_id = botai.get_bot_action(bot.role.value, alive_ids)
                if target_id and target_id in self.engine.players:
                    if current_phase == Phase.DAY_VOTING:
                        bot.vote = target_id
                    elif current_phase == Phase.NIGHT:
                        bot.night_action = target_id

            for bot_id in alive_bots:
                act_delay = random.uniform(1.0, max(1.0, duration - 1.0))
                asyncio.create_task(delayed_action(bot_id, act_delay))

    # --- CORE GAME LOOP ---
    async def run_game_loop(self):
        """The main state machine handling phases, calling the engine to resolve them."""
        self.day_counter = 0
        self.voting_history.clear()
        botai.clear_context()
        play_sound("start")

        # Secretly tell human players their roles
        for p in self.engine.get_active_players():
            if not p.is_bot and p.id in self.connections:
                teammates = []
                if p.role == Role.MAFIA:
                    teammates = [mp.name for mp in self.engine.get_active_players() if mp.role == Role.MAFIA and mp.id != p.id]
                role_packet = Packet(type=MessageType.ROLE_ASSIGNMENT, role=p.role.value, mafia_teammates=teammates)
                await self.send_packet(self.connections[p.id], role_packet)

        await self.broadcast(make_system_packet("The game has started! Roles have been assigned."))
        await self.broadcast_player_list()

        while self.engine.is_game_running:
            self.day_counter += 1
            
            # --- DAY DISCUSSION ---
            self.engine.current_phase = Phase.DAY_DISCUSSION
            play_sound("day")
            msg = f"Day {self.day_counter} begins. Discuss who is suspicious."
            await self.broadcast(Packet(
                type=MessageType.PHASE_CHANGE,
                phase=Phase.DAY_DISCUSSION.value,
                duration=DAY_DISCUSSION_DURATION,
                message=msg
            ))

            asyncio.create_task(
                self.trigger_bot_routines(DAY_DISCUSSION_DURATION)
            )
            await self.wait_phase(DAY_DISCUSSION_DURATION)
            if not self.engine.is_game_running: break
            
            # --- DAY VOTING ---
            self.engine.current_phase = Phase.DAY_VOTING
            play_sound("vote")
            msg = "Voting phase! Cast your votes to eliminate a player."
            await self.broadcast(Packet(
                type=MessageType.PHASE_CHANGE,
                phase=Phase.DAY_VOTING.value,
                duration=DAY_VOTING_DURATION,
                message=msg
            ))

            asyncio.create_task(
                self.trigger_bot_routines(DAY_VOTING_DURATION)
            )
            await self.wait_phase(DAY_VOTING_DURATION)
            if not self.engine.is_game_running: break
            
            # --- TALLY VOTES ---
            result_msg = self.engine.resolve_voting()
            await self.broadcast(Packet(type=MessageType.ELIMINATION, message=result_msg))
            await self.broadcast_player_list()
            
            if await self.check_win_condition(): break
            
            # --- NIGHT PHASE ---
            self.engine.current_phase = Phase.NIGHT
            play_sound("night")
            msg = "Night falls. The town goes to sleep. Roles awake to act."
            await self.broadcast(Packet(
                type=MessageType.PHASE_CHANGE,
                phase=Phase.NIGHT.value,
                duration=NIGHT_DURATION,
                message=msg
            ))

            asyncio.create_task(
                self.trigger_bot_routines(NIGHT_DURATION)
            )
            await self.wait_phase(NIGHT_DURATION)
            if not self.engine.is_game_running: break
            
            # --- TALLY NIGHT ACTIONS ---
            death_msg, inv_result = self.engine.resolve_night()
            await self.broadcast(Packet(type=MessageType.NIGHT_RESULT, message=death_msg))
            
            # Send private investigation result to the detective
            if inv_result and inv_result["detective_id"] in self.connections:
                target_name = inv_result["target_name"]
                is_mafia = inv_result["is_mafia"]
                inv_msg = f"Investigation Result: {target_name} is {'MAFIA' if is_mafia else 'NOT MAFIA'}."
                await self.send_packet(self.connections[inv_result["detective_id"]], Packet(type=MessageType.INVESTIGATION_RESULT, message=inv_msg))

            await self.broadcast_player_list()
            if await self.check_win_condition(): break

    async def check_win_condition(self):
        """Evaluates win conditions and triggers game end."""
        winner = self.engine.check_win_condition()
        if winner:
            await self.end_game(winner)
            return True
        return False

    async def end_game(self, winner: str):
        """Ends the match and reveals all roles."""
        self.engine.is_game_running = False
        self.engine.current_phase = Phase.GAME_OVER
        play_sound("win")
        
        botai.clear_context()
        
        # Build role summary for client table
        role_summary = {p.name: p.role.value for p in self.engine.get_active_players()}
        
        await self.broadcast(Packet(type=MessageType.GAME_OVER, winner=winner, role_summary=role_summary))
        await self.broadcast(make_system_packet("The server will return to the lobby shortly..."))
        
        # Allow players to see results, then force reset to lobby
        await asyncio.sleep(8)
        self.engine.reset_to_lobby()
        await self.broadcast_player_list()
        await self.broadcast(make_system_packet("Returned to Lobby."))

    # --- CLIENT NETWORKING ---
    async def handle_client(self, reader, writer):
        """Handles human network connections and incoming commands."""
        addr = writer.get_extra_info('peername')
        
        try:
            # 1. Wait for HANDSHAKE
            line = await reader.readline()
            if not line: return
            
            packet = Packet.decode(line)
            if packet.type != MessageType.HANDSHAKE:
                return
                
            player = self.engine.add_player(packet.name or "Human", is_bot=False)
            self.connections[player.id] = writer
            console.print(f"[cyan]Network: {player.name} connected from {addr} (ID: {player.id})[/cyan]")
            
            welcome = Packet(type=MessageType.WELCOME, player_id=player.id, message=f"Welcome to Mafia, {player.name}!")
            await self.send_packet(writer, welcome)
            await self.broadcast_player_list()

            # 2. Main Client Listening Loop
            while True:
                data = await reader.readline()
                if not data:
                    break
                
                try:
                    inc_packet = Packet.decode(data)
                    
                    if inc_packet.type == MessageType.CHAT and player.is_alive:
                        await self.broadcast(make_chat_packet(player.name, inc_packet.text or ""))
                        
                    elif inc_packet.type == MessageType.VOTE and self.engine.current_phase == Phase.DAY_VOTING and player.is_alive:
                        if inc_packet.target_id in self.engine.players:
                            player.vote = inc_packet.target_id
                            
                    elif inc_packet.type == MessageType.NIGHT_ACTION and self.engine.current_phase == Phase.NIGHT and player.is_alive:
                        if inc_packet.target_id in self.engine.players:
                            player.night_action = inc_packet.target_id

                    elif inc_packet.type == MessageType.LEAVE_TO_LOBBY:
                        break

                except Exception:
                    pass

        except Exception as e:
            console.print(f"[red]Network Error with {addr}: {e}[/red]")
        finally:
            if 'player' in locals():
                await self.handle_disconnect(player.id)

    # --- SERVER HOST CONSOLE (INSERTED) ---
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
                botai.clear_context()
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
                    # Note: We check if it's a connected human client
                    conn = self.connections.get(target_id)
                    if conn:
                        await self.send_packet(conn, Packet(type=MessageType.KICKED, message="You were kicked by the server host."))
                        await self.handle_disconnect(target_id)
                        console.print(f"[yellow]Kicked Player ID {target_id}.[/yellow]")
                    else:
                        # If it's a bot, we can just remove it from the engine directly
                        bot_player = self.engine.remove_player(target_id)
                        if bot_player:
                            await self.broadcast_player_list()
                            console.print(f"[yellow]Kicked Bot ID {target_id}.[/yellow]")
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
                console.print(f"[bold]Game Running:[/bold] {self.engine.is_game_running} | [bold]Phase:[/bold] {self.engine.current_phase.value}")

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

[bold cyan]Use [bold red]CTRL + C[/bold red] to stop the server![/bold cyan] 
""")
            else:
                console.print("[dim]Unknown host command. Type 'help' for options.[/dim]")


async def main():
    server = MafiaServer()
    net_server = await asyncio.start_server(server.handle_client, '0.0.0.0', 8888)
    
    console.print("========================================")
    console.print("[bold green][SERVER] Started on 0.0.0.0:8888[/bold green]")
    console.print("[bold green][SERVER] Interactive Host Console Ready. Type 'help' for commands.[/bold green]")
    console.print("========================================\n")
    
    await asyncio.gather(
        net_server.serve_forever(),
        server.server_operator_console()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SERVER] Server shutting down.")