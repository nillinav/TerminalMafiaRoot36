# client.py
import asyncio
import sys
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from protocol import Packet, MessageType

console = Console()

class MafiaClient:
    def __init__(self):
        self.reader = None
        self.writer = None
        self.player_id = None
        self.is_host = False
        self.my_role = None
        self.current_phase = "LOBBY"
        self.players_cache = []
        self.is_alive = True

    async def connect(self, host_ip: str, port: int, name: str):
        try:
            self.reader, self.writer = await asyncio.open_connection(host_ip, port)
        except Exception as e:
            console.print(f"[bold red]Cannot connect to {host_ip}:{port}: {e}[/bold red]")
            sys.exit(1)

        # Handshake
        handshake = Packet(type=MessageType.HANDSHAKE, name=name)
        self.writer.write(handshake.encode())
        await self.writer.drain()

        console.clear()
        console.print(Panel(f"[bold green]Connected to Server ({host_ip}:{port})[/bold green]"))

    async def send_packet(self, packet: Packet):
        try:
            self.writer.write(packet.encode())
            await self.writer.drain()
        except Exception:
            console.print("[bold red]Connection lost.[/bold red]")

    async def listen_to_server(self):
        while True:
            line = await self.reader.readline()
            if not line:
                console.print("\n[bold red]Disconnected from server.[/bold red]")
                break

            try:
                packet = Packet.decode(line)
                await self.handle_server_packet(packet)
            except ValidationError:
                pass

    async def handle_server_packet(self, packet: Packet):
        if packet.type == MessageType.WELCOME:
            self.player_id = packet.player_id
            self.is_host = packet.is_host
            console.print(f"[bold cyan]{packet.message}[/bold cyan]")
            if self.is_host:
                console.print("[bold yellow]👑 You are Host! Type '/start' when everyone has joined.[/bold yellow]")

        elif packet.type == MessageType.SYSTEM:
            console.print(f"[bold yellow][SYSTEM][/bold yellow] {packet.message}")

        elif packet.type == MessageType.CHAT:
            console.print(f"[bold cyan]{packet.sender}:[/bold cyan] {packet.text}")

        elif packet.type == MessageType.ROLE_ASSIGNMENT:
            self.my_role = packet.role
            colors = {"Mafia": "bold red", "Doctor": "bold cyan", "Detective": "bold yellow", "Villager": "bold green"}
            c = colors.get(self.my_role, "white")
            
            content = f"Secret Role: [{c}]{self.my_role.upper()}[/{c}]\n"
            if self.my_role == "Mafia" and packet.mafia_teammates:
                content += f"Teammates: {', '.join(packet.mafia_teammates)}"
            
            console.print(Panel(content, title="SECRET ROLE", border_style=c))

        elif packet.type == MessageType.PHASE_CHANGE:
            self.current_phase = packet.phase
            console.print("\n" + "="*50)
            console.print(Panel(f"[bold white]{packet.message}[/bold white]\n[dim]Duration: {packet.duration}s[/dim]", 
                                title=f"PHASE: {self.current_phase}", border_style="magenta"))
            self.print_help()

        elif packet.type == MessageType.PLAYER_LIST:
            self.players_cache = packet.players or []
            for p in self.players_cache:
                if p["id"] == self.player_id:
                    self.is_alive = p["is_alive"]

        elif packet.type == MessageType.INVESTIGATION_RESULT:
            console.print(Panel(f"[bold yellow]{packet.message}[/bold yellow]", title="INVESTIGATION REPORT", border_style="yellow"))

        elif packet.type in [MessageType.NIGHT_RESULT, MessageType.ELIMINATION]:
            console.print(Panel(f"[bold red]{packet.message}[/bold red]", border_style="red"))

        elif packet.type == MessageType.GAME_OVER:
            table = Table(title="ROLE SUMMARY")
            table.add_column("Player", style="cyan")
            table.add_column("Role", style="magenta")
            for name, role in (packet.role_summary or {}).items():
                table.add_row(name, role)

            console.print(Panel(f"[bold gold1]🎉 GAME OVER! {packet.winner} WIN! 🎉[/bold gold1]", border_style="gold1"))
            console.print(table)

        elif packet.type == MessageType.ERROR:
            console.print(f"[bold red]❌ Error: {packet.message}[/bold red]")

    def print_help(self):
        if not self.is_alive:
            console.print("[dim red]👻 You are dead. Watch or chat with other ghosts.[/dim red]")
            return

        if self.current_phase == "LOBBY":
            console.print("[dim]Type '/start' to begin (Host only) or chat.[/dim]")
        elif self.current_phase == "NIGHT":
            if self.my_role == "Mafia":
                console.print("[bold red]Type '/kill <id>' to target.[/bold red]")
            elif self.my_role == "Doctor":
                console.print("[bold cyan]Type '/save <id>' to protect.[/bold cyan]")
            elif self.my_role == "Detective":
                console.print("[bold yellow]Type '/investigate <id>' to investigate.[/bold yellow]")
        elif self.current_phase == "DAY_VOTING":
            console.print("[bold magenta]Type '/vote <id>' to vote out a player.[/bold magenta]")

    def print_players(self):
        table = Table(title="PLAYER ROOM DIRECTORY")
        table.add_column("ID", style="bold white", justify="center")
        table.add_column("Name", style="bold cyan")
        table.add_column("Status", style="bold")

        for p in self.players_cache:
            status = "[bold green]ALIVE[/bold green]" if p["is_alive"] else "[bold red]DEAD[/bold red]"
            table.add_row(str(p["id"]), p["name"], status)
        console.print(table)

    async def user_input_loop(self):
        loop = asyncio.get_running_loop()
        while True:
            raw = await loop.run_in_executor(None, input, "> ")
            text = raw.strip()
            if not text:
                continue

            if text == "/list":
                self.print_players()
            elif text == "/help":
                self.print_help()
            elif text == "/start" and self.current_phase == "LOBBY":
                await self.send_packet(Packet(type=MessageType.START_GAME))
            elif text.startswith("/kill ") and self.current_phase == "NIGHT":
                try:
                    await self.send_packet(Packet(type=MessageType.NIGHT_ACTION, target_id=int(text.split()[1])))
                except ValueError:
                    console.print("[red]Usage: /kill <player_id>[/red]")
            elif text.startswith("/save ") and self.current_phase == "NIGHT":
                try:
                    await self.send_packet(Packet(type=MessageType.NIGHT_ACTION, target_id=int(text.split()[1])))
                except ValueError:
                    console.print("[red]Usage: /save <player_id>[/red]")
            elif text.startswith("/investigate ") and self.current_phase == "NIGHT":
                try:
                    await self.send_packet(Packet(type=MessageType.NIGHT_ACTION, target_id=int(text.split()[1])))
                except ValueError:
                    console.print("[red]Usage: /investigate <player_id>[/red]")
            elif text.startswith("/vote ") and self.current_phase == "DAY_VOTING":
                try:
                    await self.send_packet(Packet(type=MessageType.VOTE, target_id=int(text.split()[1])))
                except ValueError:
                    console.print("[red]Usage: /vote <player_id>[/red]")
            else:
                await self.send_packet(Packet(type=MessageType.CHAT, text=text))

async def main():
    console.print(Panel("[bold cyan]MAFIA CLI CLIENT[/bold cyan]"))
    host_ip = input("Enter Server IP (Default: 127.0.0.1): ").strip() or "127.0.0.1"
    name = input("Enter Player Name: ").strip() or "Player"

    client = MafiaClient()
    await client.connect(host_ip, 8888, name)

    await asyncio.gather(
        client.listen_to_server(),
        client.user_input_loop()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Left the game.[/yellow]")