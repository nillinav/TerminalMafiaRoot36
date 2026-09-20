import asyncio
import sys
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Import the robust audio methods
from audio import play_audio, stop_audio, wait_audio
from protocol import Packet, MessageType

SOUND_EFFECTS = Path(__file__).resolve().parent / "sound_effects"
day_music = SOUND_EFFECTS / "day_music.mp3"
night_music = SOUND_EFFECTS / "night_music.mp3"
kill_sfx = SOUND_EFFECTS / "kill_sfx.mp3"
victory_sfx = SOUND_EFFECTS / "victory_sfx.mp3"
defeat_sfx = SOUND_EFFECTS / "defeat_sfx.mp3"
bell_sfx = SOUND_EFFECTS / "bell_sfx.mp3"
reveal_sfx = SOUND_EFFECTS / "reveal_sfx.mp3"

console = Console()

role_colors = {"Mafia": "bold red", "Doctor": "bold cyan", "Detective": "bold yellow", "Villager": "bold green"}

role_ascii = {
    "Mafia":
r"""    ________________                    ________________ 
~~~ \__________     \________  ________/     __________/~~~
               \__      ______/           __/               
                  \____/            _____/                  
                 /                _/      \                 
________________/                /         \________________
|              ___   ___ ___ \ \ \_ ___   __               |
\            _/  |   |  // /\ \ \ \\  |   |  \_            /
 \         _/    |   |_// / /\ \ \ \\_|   |    \_         / 
  \       /      |   | / / / /\ \ \ \ |   |      \       /  
   \    /        |___|/ / / /  \ \ \ \|___|        \    /   
    \__/            /______/    \______\            \__/   """,

    "Villager":
r"""⠀⠀⠀⠀⠀⠀⠀⢀⡠⠔⠊⠀⠀⠀⠀⠀⠀⠀⠀⠒⠤⡀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⢸⠓⠤⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡠⠔⢲⠀⠀
⠀⠀⠀⠀⠀⠀⢸⠀⠀⠀⠉⠒⠤⣀⠀⢀⡠⠔⠊⠁⠀⠈⢸⠀⠀
⠀⠀⠀⠀⠀⠀⢸⠀⠀⠀⠀⠀⠀⠀⢹⠁⠀⠀⠀⠀⠀⠀⢸⠀⠀
⠀⠀⠀⠀⠀⠀⢸⢠⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⠀⠀
⠀⠀⠀⠀⠀⠠⣸⢬⣹⣿⢷⣦⣄⡀⢠⠀⠀⠀⠀⠀⠀⠀⢸⠀⠀
⠀⠀⠀⠀⡠⢣⢾⠸⡐⠉⠒⣼⣿⠻⢸⠀⠀⠀⠀⠀⠀⠀⢸⠀⠀
⠀⠀⠀⡐⠡⠃⢺⢢⠀⢹⣿⣿⣦⢩⢺⠀⠀⠀⢠⡠⣔⣮⣿⠀⠀
⠀⠀⡜⠀⠀⢀⠸⣿⠀⢸⣿⣿⠌⢘⢸⣠⣔⣾⣷⣿⣿⣿⣿⠀⠀
⢀⠌⡀⠀⠀⠮⠜⠙⢲⢼⣿⣿⣾⡿⣿⢻⣿⢏⢄⡉⡛⣿⣿⠀⠀
⠎⡀⠲⢀⣀⠐⡴⢈⢁⠮⣜⡑⢫⢷⣼⣿⠋⠀⠂⢜⣱⣿⣿⣦⡄
⠀⠈⠳⢦⣄⡉⠀⢠⢋⠜⡔⣀⢑⠄⣜⡐⠀⠀⠀⣴⣿⣿⣿⡟⠀
⠀⠀⠀⠀⠈⠙⢳⣧⣎⡌⡐⠁⢈⠆⠘⠀⠀⠀⣼⣿⣿⣿⣿⠀⠀
⠀⠀⠀⠀⠀⠀⢸⣿⠿⠙⣷⣦⣄⡕⠀⠤⢂⣾⣿⣿⣿⣿⣿⠀⠀
⠀⠀⠀⠀⠀⠀⢸⠿⠀⠀⣿⣿⡏⠙⠳⢦⣾⣿⣿⣿⣿⣿⣿⠀⠀
⠀⠀⠀⠀⠀⠀⢸⢠⣤⠀⣿⣿⡇⠀⢸⣾⣿⣿⣿⣿⣿⣿⣿⠀⠀""",

    "Doctor":
r"""           ⣠⣶⣿⣻⣫⣿⣿⣶⣦   
         ⣴⣿⡿⢟⣭⣿⣯⣯⣽⣿⣾⣗⣆ 
       |======(⊙)=====|
       ⢸⣿⡏           ⣻⡇
       ⢈⣿⡇ ⣀⣀⣀  ⢀⣠⣤⣀ ⣿⡁
       ⣿⡝ ⠋<O>   <O> ⢯⣿
       ⡯⣿     ⡀⠸⣄    ⢿⡞
       ⠘⠯⡇⢀⢀⡴⠛⠒⠰⠚  ⣠⢠⠟⠁
         ⢳⠘ ⠙⠯⣭⣭⡿⠁ ⡇⡞  
          ⠱⣄   ⠂ ⣨⠞   
            ⠑⡞  ⡏⠚⠁    
           ⣠⡀⠲⣿⣿⠖⢀⣄           
       ⢀⣿⣿⣧⠈⢿⣄⠙⠋⣠⡿⠁⣼⣿⣿⡀       
       ⢸⣿⣿⠿⣷⡀⠙⠇⠸⠋⢀⣾⠿⣿⣿⡇       
       ⣿⣿⡏⢠⣿⣿⣶⡄⢠⣶⡟⢻⡄⢻⣿⣿       
      ⢰⣿⣿⠇⢸⣿⣿⣿⡇⠈⢉⣀⡈⡇⢸⣿⣿⡆      
      ⣾⣿⣿ ⣸⣿⣿⣿⡇ ⠸⠿⠇⣇ ⣿⣿⣷      
      ⠻⠿⠏ ⣿⣿⣿⣿⡇⢸⣶⣶⣶⣿ ⠹⠿⠟      
    
                             
""",

    "Detective":
r"""        ⢶⣦⣿⣤⣤⣤⣤⣀⣀                 
      ⣠⣶⣿⡟⠛⠿⣿⣍⡉⠙⠛⠿⣶⣄              
    ⣠⣾⠏⣿⡟⣀⠂⡐⠘⢿⣿⡠⢁⠂⠌⠻⣷⣄            
   ⣰⡿⢁⠸⣿⠇⢠⠂⠡⠌⣀⢻⣷⡁⠌⢂⠡⠈⢿⣧           
  ⢰⡿⢠⠁⢺⣿⡇⢠⠈⡁⠆⡀⠂⢿⣧⠈⠄⢂⣁⣂⣿⣧⡀         
  ⢾⡗⠸⢀⠉⣿⣧⢀⠂⡁⢂⢤⣡⣼⣿⣾⡾⠿⢛⠛⠩⠙⠻⢷⣤⣀      
  ⢿⡇⢁⠂⣤⣹⣿⣦⣶⣿⣿⡟⠋⠉⠈⠙⠻⣾⣥⣬⣠⣁⣆⣤⣭⣿⠿     
  ⢸⣿⣾⠿⠟⣻⣿⣿⠿⠿⣿⠁      ⠈⠉⠙⣿⠛⠉⠉       
  ⣾⠏⡀⢢⣼⣿⣿⠁           <O>⢹⣇         
 ⣰⡿⣀⣥⣾⣿⣿⣿⡀             ⠈⣿         
 ⠿⠟⠛⠉⢹⣿⣿⣿⣷⣦           ⢠⣤⣽⡇       ~~~           
    ⣰⡿⠻⠿⣿⣿⣇           ⢸⡇        S S          
   ⣴⡟⠃⠤⢁⠤⠉⠛⠻⣶⣤⣀       ⢸⡿⢷⣦⡀    S S            
 ⢀⣾⠿⠈⡘⢠⠁⢂⠩⠄⢡ ⡉⠛⢷⣦⣄⣀⡀  ⣸⡇ ⠙⣷⡄ ⢀⣶⣶⣶⣶
⢠⣿⣏⡤⡁⠌⠠⠘⠠⢁⠊⡄⢒⠠⢃⠄⡌⠻⣿⣟⠛⠛⠋   ⠘⣿⣦⣼⣿⣿⣿⡿
 ⠙⠛⠛⠛⠿⠿⠷⣶⣧⣴⣤⣈⡐⢈⠐⠠⠃⡀⠻⣷⣄     ⠘⠻⢿⣿⠿⠟⠁
          ⠉⠉⠙⠛⠿⠷⣾⣤⣴⣁⡈⠿⣧⡀          
                 ⠈⠉⠛⠻⠷⣿⡇          """
}

class MafiaClientUI:
    def __init__(self):
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.player_id: Optional[int] = None
        self.my_role: Optional[str] = None
        self.current_phase: str = "LOBBY"
        self.players_cache: List[Dict[str, Any]] = []
        self.is_alive: bool = True
        self.in_active_game: bool = False
        self.running: bool = True  # Controls the main loops
        self.audio_task: Optional[asyncio.Task] = None

    # ==========================================
    # AUDIO MANAGER SYSTEM
    # ==========================================
    def _cancel_audio_task(self):
        """Cancels any running audio sequences and completely stops the audio player."""
        if self.audio_task and not self.audio_task.done():
            self.audio_task.cancel()
        self.audio_task = None
        stop_audio()

    async def _play_sequence(self, sequence: List[Path], loop_last: bool = False):
        """
        Plays a list of audio files in sequence.
        If loop_last is True, the final audio file will repeat endlessly until cancelled.
        """
        try:
            for i, sound_path in enumerate(sequence):
                if not sound_path.is_file():
                    console.print(f"[dim red]Warning: Audio file missing: {sound_path}[/dim red]")
                    continue
                
                is_last_item = (i == len(sequence) - 1)
                
                while True:
                    # 1. Start playback immediately
                    play_audio(sound_path)
                    
                    # 2. Block this specific coroutine until the file finishes playing
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, wait_audio)
                    
                    # 3. If it's not the last item, or we aren't supposed to loop it, move on.
                    if not (loop_last and is_last_item):
                        break

        except asyncio.CancelledError:
            # Expected behavior when transitioning phases/cutting off audio
            stop_audio()
        except Exception as e:
            console.print(f"[dim red]Audio playback sequence interrupted: {e}[/dim red]")
            stop_audio()

    def _trigger_audio(self, sequence: List[Path], loop_last: bool = False):
        """Helper to cleanly stop current audio and start a new sequence background task."""
        self._cancel_audio_task()
        self.audio_task = asyncio.create_task(self._play_sequence(sequence, loop_last))

    # ==========================================
    # NETWORK PROTOCOL & GAME LOGIC
    # ==========================================
    async def connect(self, host_ip: str, port: int, name: str):
        try:
            self.reader, self.writer = await asyncio.open_connection(host_ip, port)
        except Exception as e:
            console.print(f"[bold red]Unable to connect to {host_ip}:{port} - {e}[/bold red]")
            sys.exit(1)

        # Handshake
        handshake = Packet(type=MessageType.HANDSHAKE, name=name)
        await self.send_packet(handshake)

        console.clear()
        console.print(Panel(f"[bold green]Connected to Mafia Game Server ({host_ip}:{port})[/bold green]"))

    async def send_packet(self, packet: Packet):
        if not self.writer:
            return
        try:
            self.writer.write(packet.encode())
            await self.writer.drain()
        except (ConnectionError, OSError) as e:
            console.print(f"[bold red]Error sending data: {e}[/bold red]")
            self.running = False

    async def listen_loop(self):
        """Listens for server messages in the background."""
        while self.running:
            try:
                line = await self.reader.readline()
                if not line:
                    console.print("\n[bold red]Server closed the connection.[/bold red]")
                    self.running = False
                    break

                try:
                    packet = Packet.decode(line)
                    await self.handle_packet(packet)
                except (ValidationError, json.JSONDecodeError):
                    console.print(f"[dim red]Received malformed packet from server (ignored).[/dim red]")

            except (asyncio.IncompleteReadError, ConnectionError, OSError):
                console.print("\n[bold red]Connection to host lost.[/bold red]")
                self.running = False
                break

    async def handle_packet(self, packet: Packet):
        """Routes instructions from the server to the rich console and audio engine."""
        if packet.type == MessageType.WELCOME:
            self.player_id = packet.player_id
            console.print(f"[bold cyan]{packet.message}[/bold cyan]")

        elif packet.type == MessageType.LOBBY_WAIT:
            self.in_active_game = False
            self._cancel_audio_task()  # Silence in lobby
            console.print(Panel(f"[bold yellow]{packet.message}[/bold yellow]", title="SPECTATOR LOBBY"))

        elif packet.type == MessageType.SYSTEM:
            console.print(f"[bold yellow][SYSTEM][/bold yellow] {packet.message}")

        elif packet.type == MessageType.CHAT:
            console.print(f"[bold cyan]{packet.sender}:[/bold cyan] {packet.text}")

        elif packet.type == MessageType.ROLE_ASSIGNMENT:
            self.my_role = packet.role
            self.in_active_game = True
            self.is_alive = True
            
            # AUDIO: Play player reveal sound
            self._trigger_audio([reveal_sfx], loop_last=False)
            
            c = role_colors.get(self.my_role, "white")
            art = role_ascii.get(self.my_role, role_ascii["Villager"])
            
            content = f"Secret Role: [{c}]{self.my_role.upper()}\n"
            content += art + f"[/{c}]\n"
            if self.my_role == "Mafia" and getattr(packet, "mafia_teammates", None):
                content += f"Mafia Allies: {', '.join(packet.mafia_teammates)}"
            
            console.print(Panel(content, title="SECRET ROLE REVEAL", border_style=c))

        elif packet.type == MessageType.PHASE_CHANGE:
            self.current_phase = packet.phase
            console.print("\n" + "="*50)
            
            # AUDIO: Map phases to sound effects
            if self.current_phase == "DAY_DISCUSSION":
                self._trigger_audio([bell_sfx, day_music], loop_last=True)
            elif self.current_phase == "DAY_VOTING":
                self._cancel_audio_task() # Silent during voting
            elif self.current_phase == "NIGHT":
                self._trigger_audio([night_music], loop_last=True)
            
            duration = getattr(packet, "duration", 0)
            console.print(Panel(f"[bold white]{packet.message}[/bold white]\n[dim]Duration: {duration} seconds[/dim]", 
                                title=f"PHASE: {self.current_phase}", border_style="magenta"))
            self.display_context_actions()

        elif packet.type == MessageType.PLAYER_LIST:
            self.players_cache = packet.players or []
            for p in self.players_cache:
                if p.get("id") == self.player_id:
                    self.is_alive = p.get("is_alive", True)
                    self.in_active_game = p.get("in_active_game", False)

        elif packet.type == MessageType.INVESTIGATION_RESULT:
            console.print(Panel(f"[bold yellow]{packet.message}[/bold yellow]", title="DETECTIVE REPORT", border_style="yellow"))

        elif packet.type in [MessageType.NIGHT_RESULT, MessageType.ELIMINATION]:
            # AUDIO: Check if someone was killed based on message contents
            msg_lower = packet.message.lower()
            if "died" in msg_lower or "killed" in msg_lower or "eliminated" in msg_lower or "murdered" in msg_lower:
                self._trigger_audio([kill_sfx], loop_last=False)
            
            console.print(Panel(f"[bold red]{packet.message}[/bold red]", border_style="red"))

        elif packet.type == MessageType.GAME_OVER:
            self.in_active_game = False
            table = Table(title="MATCH REVEAL")
            table.add_column("Player", style="cyan")
            table.add_column("Role", style="magenta")
            
            role_summary = getattr(packet, "role_summary", {})
            if role_summary:
                for name, role in role_summary.items():
                    table.add_row(str(name), str(role))
                
            # AUDIO: Evaluate if this player was on the winning team
            if packet.winner:
                player_won = (
                    (packet.winner.lower() == "mafia" and self.my_role == "Mafia")
                    or (packet.winner.lower() != "mafia" and self.my_role != "Mafia")
                )
                if player_won:
                    console.print(Panel(f"[bold gold1]🎉 VICTORY! {packet.winner} WIN! 🎉[/bold gold1]", border_style="gold1"))
                    self._trigger_audio([victory_sfx], loop_last=False)
                else:
                    console.print(Panel(f"[bold red]☠️ DEFEAT! {packet.winner} WIN! ☠️[/bold red]", border_style="red"))
                    self._trigger_audio([defeat_sfx], loop_last=False)
            if role_summary:
                console.print(table)

        elif packet.type == MessageType.KICKED:
            self._cancel_audio_task()
            console.print(Panel(f"[bold red]{packet.message}[/bold red]", title="KICKED"))
            self.running = False

        elif packet.type == MessageType.ERROR:
            console.print(f"[bold red]❌ {packet.message}[/bold red]")

    def display_context_actions(self):
        """Displays formatted menu based on the current phase."""
        if not self.in_active_game:
            console.print("[dim]Type text to chat in lobby. Type '/list' to view players.[/dim]")
            return

        if not self.is_alive:
            console.print("[dim red]👻 You are dead. Type text to chat with other ghosts.[/dim red]")
            return

        if self.current_phase in ["NIGHT", "DAY_VOTING"]:
            self.display_action_menu()

    def display_action_menu(self):
        """Displays a table (CLI Dropdown) of alive players for target selection."""
        valid_targets = [p for p in self.players_cache if p.get("in_active_game") and p.get("is_alive")]
        
        if not valid_targets:
            console.print("[dim yellow]Awaiting player data...[/dim yellow]")
            return

        table = Table(title="TARGET MENU", border_style="cyan")
        table.add_column("ID", justify="center", style="bold yellow")
        table.add_column("Player Name", style="bold white")
        
        for p in valid_targets:
            table.add_row(str(p.get("id")), str(p.get("name")))
            
        console.print(table)
        
        if self.current_phase == "NIGHT" and self.my_role != "Villager":
            action = "eliminate" if self.my_role == "Mafia" else "protect" if self.my_role == "Doctor" else "investigate"
            console.print(f"👉 [bold cyan]Enter the [yellow]ID[/yellow] of the player you want to {action}.[/bold cyan]")
        elif self.current_phase == "DAY_VOTING":
            console.print("👉 [bold magenta]Enter the [yellow]ID[/yellow] of the player you want to vote out.[/bold magenta]")

    def display_player_table(self):
        """Renders the full directory (for /list command)."""
        if not self.players_cache:
            console.print("[yellow]No player data available yet.[/yellow]")
            return

        table = Table(title="ROOM PLAYER DIRECTORY")
        table.add_column("ID", justify="center")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("In Active Match?")

        for p in self.players_cache:
            st = "[bold green]ALIVE[/bold green]" if p.get("is_alive") else "[bold red]DEAD[/bold red]"
            ingame = "YES" if p.get("in_active_game") else "NO (Lobby)"
            table.add_row(str(p.get("id", "?")), str(p.get("name", "Unknown")), st, ingame)

        console.print(table)

    async def user_input_loop(self):
        """Dedicated thread for pure text input commands."""
        loop = asyncio.get_running_loop()
        while self.running:
            try:
                # readline instead of input() prevents the prompt cursor from mangling async messages
                raw = await loop.run_in_executor(None, sys.stdin.readline)
                
                if not raw:  # EOF triggered (e.g. Ctrl+D)
                    self.running = False
                    break
                    
                text = raw.strip()
                if not text:
                    continue

                # 1) Command checks
                if text == "/list":
                    self.display_player_table()
                    continue
                elif text == "/leave":
                    await self.send_packet(Packet(type=MessageType.LEAVE_TO_LOBBY))
                    continue
                elif text in ["/quit", "/exit"]:
                    self.running = False
                    break

                # 2) Action Target Input (Replaces /act and /vote)
                if text.isdigit() and self.in_active_game and self.is_alive and self.current_phase in ["NIGHT", "DAY_VOTING"]:
                    target_id = int(text)
                    valid_ids = [p.get("id") for p in self.players_cache if p.get("in_active_game") and p.get("is_alive")]
                    
                    if target_id in valid_ids:
                        packet_type = MessageType.NIGHT_ACTION if self.current_phase == "NIGHT" else MessageType.VOTE
                        await self.send_packet(Packet(type=packet_type, target_id=target_id))
                        console.print(f"[dim green]✔ Action locked in for ID {target_id}.[/dim green]")
                    else:
                        console.print(f"[bold red]❌ Error: '{target_id}' is not a valid ID from the target menu.[/bold red]")
                    continue

                # 3) Fallback to normal chat
                await self.send_packet(Packet(type=MessageType.CHAT, text=text))
                    
            except Exception as e:
                console.print(f"[red]Input error: {e}[/red]")
                break

    async def close(self):
        """Safely clean up socket connections and audio tasks."""
        self.running = False
        self._cancel_audio_task()
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass


async def main():
    console.print(Panel("[bold cyan]LARPING US[/bold cyan]"))
    
    host_ip = "127.0.0.1"
    try:
        # host_ip = input("Enter Server Host IP (default 127.0.0.1): ").strip() or "127.0.0.1"
        name = input("Enter Player Name: ").strip() or "Player"
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Setup cancelled. Exiting.[/yellow]")
        return

    client = MafiaClientUI()
    await client.connect(host_ip, 8888, name)

    # Run background listener and user input simultaneously
    listen_task = asyncio.create_task(client.listen_loop())
    input_task = asyncio.create_task(client.user_input_loop())
    
    # Wait until either the listener fails (server crash) or input stops (user types /quit)
    done, pending = await asyncio.wait(
        [listen_task, input_task], 
        return_when=asyncio.FIRST_COMPLETED
    )

    # Cancel whatever task is still running to ensure clean exit
    for task in pending:
        task.cancel()
        
    await client.close()
    console.print("\n[yellow]Client shut down safely.[/yellow]")


if __name__ == "__main__":
    try:
        # Standard way to run asyncio on Python 3.7+
        asyncio.run(main())
    except KeyboardInterrupt:
        # Catch hard exits (Ctrl+C) so they don't print nasty tracebacks
        stop_audio()