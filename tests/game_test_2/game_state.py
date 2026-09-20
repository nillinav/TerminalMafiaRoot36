# game_state.py
from enum import Enum
import random
from typing import Dict, List, Optional, Tuple


class Role(str, Enum):
    MAFIA = "Mafia"
    VILLAGER = "Villager"
    DOCTOR = "Doctor"
    DETECTIVE = "Detective"


class Phase(str, Enum):
    LOBBY = "LOBBY"
    NIGHT = "NIGHT"
    DAY_DISCUSSION = "DAY_DISCUSSION"
    DAY_VOTING = "DAY_VOTING"
    GAME_OVER = "GAME_OVER"


class PlayerState:
    def __init__(self, player_id: int, name: str, is_bot: bool = False):
        self.id = player_id
        self.name = name
        self.role: Role = Role.VILLAGER
        self.is_alive: bool = True
        self.is_bot: bool = is_bot
        self.in_active_game: bool = False
        self.night_action: Optional[int] = None
        self.vote: Optional[int] = None

    def reset_for_game(self):
        self.is_alive = True
        self.night_action = None
        self.vote = None
        self.role = Role.VILLAGER
        self.in_active_game = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "is_alive": self.is_alive,
            "in_active_game": self.in_active_game
        }


class GameEngine:
    def __init__(self, min_players: int = 4):
        self.min_players = min_players
        self.players: Dict[int, PlayerState] = {}
        self.current_phase: Phase = Phase.LOBBY
        self.next_id = 1
        self.is_game_running: bool = False

    def add_player(self, name: str, is_bot: bool = False) -> PlayerState:
        # Enforce unique name handling
        existing_names = [p.name for p in self.players.values()]
        unique_name = name
        counter = 1
        while unique_name in existing_names:
            unique_name = f"{name}_{counter}"
            counter += 1

        player = PlayerState(self.next_id, unique_name, is_bot=is_bot)
        # If game is already running, player waits in lobby queue
        player.in_active_game = not self.is_game_running
        self.players[player.id] = player
        self.next_id += 1
        return player

    def remove_player(self, player_id: int) -> Optional[PlayerState]:
        return self.players.pop(player_id, None)

    def start_game(self) -> bool:
        """Starts a game using available lobby players."""
        eligible = [p for p in self.players.values() if not p.in_active_game or self.current_phase == Phase.LOBBY]
        if len(eligible) < self.min_players:
            return False

        self.is_game_running = True
        self.current_phase = Phase.NIGHT

        # Reset and mark active
        for p in eligible:
            p.reset_for_game()

        # Assign Roles
        random.shuffle(eligible)
        n = len(eligible)
        num_mafia = max(1, n // 4)

        for i, p in enumerate(eligible):
            if i < num_mafia:
                p.role = Role.MAFIA
            elif i == num_mafia:
                p.role = Role.DOCTOR
            elif i == num_mafia + 1 and n >= 5:
                p.role = Role.DETECTIVE
            else:
                p.role = Role.VILLAGER

        return True

    def reset_to_lobby(self):
        """Resets room state and moves all players into the lobby."""
        self.is_game_running = False
        self.current_phase = Phase.LOBBY
        for p in self.players.values():
            p.in_active_game = False
            p.is_alive = True
            p.night_action = None
            p.vote = None

    def get_active_players(self) -> List[PlayerState]:
        return [p for p in self.players.values() if p.in_active_game]

    def get_alive_players(self) -> List[PlayerState]:
        return [p for p in self.players.values() if p.in_active_game and p.is_alive]

    def resolve_night(self) -> Tuple[str, Optional[dict]]:
        mafia_targets = []
        doctor_target = None
        detective_target = None
        detective_id = None

        for p in self.get_alive_players():
            if p.role == Role.MAFIA and p.night_action:
                mafia_targets.append(p.night_action)
            elif p.role == Role.DOCTOR:
                doctor_target = p.night_action
            elif p.role == Role.DETECTIVE:
                detective_target = p.night_action
                detective_id = p.id

        killed_id = None
        if mafia_targets:
            killed_id = max(set(mafia_targets), key=mafia_targets.count)

        inv_result = None
        if detective_id and detective_target and detective_target in self.players:
            target = self.players[detective_target]
            inv_result = {
                "detective_id": detective_id,
                "target_name": target.name,
                "is_mafia": (target.role == Role.MAFIA)
            }

        death_msg = "🌅 The night passed quietly. Nobody was killed."
        if killed_id and killed_id in self.players:
            if killed_id == doctor_target:
                death_msg = "🛡️ Someone was targeted by Mafia, but protected by the Doctor!"
            else:
                victim = self.players[killed_id]
                victim.is_alive = False
                death_msg = f"☠️ {victim.name} was eliminated during the night! Role: {victim.role.value}."

        for p in self.players.values():
            p.night_action = None

        return death_msg, inv_result

    def resolve_voting(self) -> str:
        votes: Dict[int, int] = {}
        for p in self.get_alive_players():
            if p.vote and p.vote in self.players:
                votes[p.vote] = votes.get(p.vote, 0) + 1
            p.vote = None

        if not votes:
            return "🗳️ No votes cast. Nobody was eliminated."

        max_v = max(votes.values())
        top_targets = [tid for tid, count in votes.items() if count == max_v]

        if len(top_targets) > 1:
            return "⚖️ Voting ended in a tie! Nobody was eliminated."

        eliminated = self.players[top_targets[0]]
        eliminated.is_alive = False
        return f"💀 {eliminated.name} was eliminated by vote! Role: {eliminated.role.value}."

    def check_win_condition(self) -> Optional[str]:
        if not self.is_game_running:
            return None

        alive_mafia = [p for p in self.get_alive_players() if p.role == Role.MAFIA]
        alive_town = [p for p in self.get_alive_players() if p.role != Role.MAFIA]

        if len(alive_mafia) == 0:
            return "VILLAGERS"
        if len(alive_mafia) >= len(alive_town):
            return "MAFIA"
        return None