# game_state.py
from enum import Enum
import random
from typing import Dict, Optional, Tuple


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
    def __init__(self, player_id: int, name: str):
        self.id = player_id
        self.name = name
        self.role: Role = Role.VILLAGER
        self.is_alive: bool = True
        self.night_action: Optional[int] = None
        self.vote: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "is_alive": self.is_alive
        }


class GameState:
    def __init__(self, min_players: int = 4):
        self.min_players = min_players
        self.players: Dict[int, PlayerState] = {}
        self.current_phase: Phase = Phase.LOBBY
        self.next_id = 1
        self.host_id: Optional[int] = None

    def add_player(self, name: str) -> PlayerState:
        player = PlayerState(self.next_id, name)
        if not self.players:
            self.host_id = player.id
        self.players[player.id] = player
        self.next_id += 1
        return player

    def remove_player(self, player_id: int) -> Optional[PlayerState]:
        player = self.players.pop(player_id, None)
        if player_id == self.host_id and self.players:
            self.host_id = next(iter(self.players.keys()))
        return player

    def assign_roles(self):
        player_list = list(self.players.values())
        random.shuffle(player_list)

        n = len(player_list)
        num_mafia = max(1, n // 4)

        for i, player in enumerate(player_list):
            if i < num_mafia:
                player.role = Role.MAFIA
            elif i == num_mafia:
                player.role = Role.DOCTOR
            elif i == num_mafia + 1 and n >= 5:
                player.role = Role.DETECTIVE
            else:
                player.role = Role.VILLAGER

    def resolve_night(self) -> Tuple[str, Optional[dict]]:
        mafia_targets = []
        doctor_target = None
        detective_target = None
        detective_id = None

        for p in self.players.values():
            if not p.is_alive:
                continue
            if p.role == Role.MAFIA and p.night_action:
                mafia_targets.append(p.night_action)
            elif p.role == Role.DOCTOR:
                doctor_target = p.night_action
            elif p.role == Role.DETECTIVE:
                detective_target = p.night_action
                detective_id = p.id

        killed_player_id = None
        if mafia_targets:
            killed_player_id = max(set(mafia_targets), key=mafia_targets.count)

        investigation_result = None
        if detective_id and detective_target and detective_target in self.players:
            target = self.players[detective_target]
            investigation_result = {
                "detective_id": detective_id,
                "target_name": target.name,
                "is_mafia": (target.role == Role.MAFIA)
            }

        if killed_player_id and killed_player_id in self.players:
            if killed_player_id == doctor_target:
                death_msg = "🛡️ Someone was targeted by the Mafia, but saved by the Doctor!"
            else:
                victim = self.players[killed_player_id]
                victim.is_alive = False
                death_msg = f"☠️ {victim.name} was murdered during the night! Role: {victim.role.value}."
        else:
            death_msg = "🌅 The night passed peacefully. Nobody died."

        for p in self.players.values():
            p.night_action = None

        return death_msg, investigation_result

    def resolve_voting(self) -> str:
        votes: Dict[int, int] = {}
        for p in self.players.values():
            if p.is_alive and p.vote in self.players:
                votes[p.vote] = votes.get(p.vote, 0) + 1

        for p in self.players.values():
            p.vote = None

        if not votes:
            return "🗳️ No votes cast. Nobody was eliminated."

        max_votes = max(votes.values())
        top_targets = [tid for tid, count in votes.items() if count == max_votes]

        if len(top_targets) > 1:
            return "⚖️ Voting ended in a tie! Nobody was eliminated."

        eliminated = self.players[top_targets[0]]
        eliminated.is_alive = False
        return f"💀 {eliminated.name} was voted out! Role: {eliminated.role.value}."

    def check_win_condition(self) -> Optional[str]:
        alive_mafia = [p for p in self.players.values() if p.is_alive and p.role == Role.MAFIA]
        alive_town = [p for p in self.players.values() if p.is_alive and p.role != Role.MAFIA]

        if len(alive_mafia) == 0:
            return "VILLAGERS"
        if len(alive_mafia) >= len(alive_town):
            return "MAFIA"
        return None