import asyncio
import sys
import json
from typing import List, Dict, Any, Optional
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Make sure this matches your actual protocol file name
from protocol import Packet, MessageType

console = Console()


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
        """Routes instructions from the server to the rich console."""
        if packet.type == MessageType.WELCOME:
            self.player_id = packet.player_id
            console.print(f"[bold cyan]{packet.message}[/bold cyan]")

        elif packet.type == MessageType.LOBBY_WAIT:
            self.in_active_game = False
            console.print(Panel(f"[bold yellow]{packet.message}[/bold yellow]", title="SPECTATOR LOBBY"))

        elif packet.type == MessageType.SYSTEM:
            console.print(f"[bold yellow][SYSTEM][/bold yellow] {packet.message}")

        elif packet.type == MessageType.CHAT:
            console.print(f"[bold cyan]{packet.sender}:[/bold cyan] {packet.text}")

        elif packet.type == MessageType.ROLE_ASSIGNMENT:
            self.my_role = packet.role
            self.in_active_game = True
            self.is_alive = True
            colors = {"Mafia": "bold red", "Doctor": "bold cyan", "Detective": "bold yellow", "Villager": "bold green"}
            c = colors.get(self.my_role, "white")
            
            content = f"Secret Role: [{c}]{self.my_role.upper()}[/{c}]\n"
            if self.my_role == "Mafia" and getattr(packet, "mafia_teammates", None):
                content += f"Mafia Allies: {', '.join(packet.mafia_teammates)}"
            
            console.print(Panel(content, title="SECRET ROLE REVEAL", border_style=c))

        elif packet.type == MessageType.PHASE_CHANGE:
            self.current_phase = packet.phase
            console.print("\n" + "="*50)
            
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

            console.print(Panel(f"[bold gold1]🎉 GAME OVER! {packet.winner} WIN! 🎉[/bold gold1]", border_style="gold1"))
            if role_summary:
                console.print(table)

        elif packet.type == MessageType.KICKED:
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
        
        if self.current_phase == "NIGHT":
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
                # If the user types only numbers during an action phase, handle it as an ID submission
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
        """Safely clean up socket connections."""
        self.running = False
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass


async def main():
    console.print(Panel("[bold cyan]MAFIA CLI CLIENT[/bold cyan]"))
    
    try:
        host_ip = input("Enter Server Host IP (default 127.0.0.1): ").strip() or "127.0.0.1"
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
        pass