# protocol.py
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class MessageType(str, Enum):
    # Client -> Server
    HANDSHAKE = "HANDSHAKE"
    CHAT = "CHAT"
    NIGHT_ACTION = "NIGHT_ACTION"
    VOTE = "VOTE"
    LEAVE_TO_LOBBY = "LEAVE_TO_LOBBY"
    
    # Server -> Client
    WELCOME = "WELCOME"
    SYSTEM = "SYSTEM"
    ROLE_ASSIGNMENT = "ROLE_ASSIGNMENT"
    PHASE_CHANGE = "PHASE_CHANGE"
    PLAYER_LIST = "PLAYER_LIST"
    INVESTIGATION_RESULT = "INVESTIGATION_RESULT"
    NIGHT_RESULT = "NIGHT_RESULT"
    ELIMINATION = "ELIMINATION"
    GAME_OVER = "GAME_OVER"
    LOBBY_WAIT = "LOBBY_WAIT"
    ERROR = "ERROR"
    KICKED = "KICKED"


class Packet(BaseModel):
    """Type-validated network packet DTO."""
    type: MessageType
    name: Optional[str] = None
    text: Optional[str] = None
    target_id: Optional[int] = None
    sender: Optional[str] = None
    player_id: Optional[int] = None
    role: Optional[str] = None
    mafia_teammates: Optional[List[str]] = None
    phase: Optional[str] = None
    duration: Optional[int] = None
    message: Optional[str] = None
    players: Optional[List[Dict[str, Any]]] = None
    winner: Optional[str] = None
    role_summary: Optional[Dict[str, str]] = None

    def encode(self) -> bytes:
        return (self.model_dump_json(exclude_none=True) + "\n").encode("utf-8")

    @classmethod
    def decode(cls, raw_line: bytes) -> "Packet":
        return cls.model_validate_json(raw_line.decode("utf-8").strip())


def make_system_packet(text: str) -> Packet:
    return Packet(type=MessageType.SYSTEM, message=text)

def make_error_packet(error_msg: str) -> Packet:
    return Packet(type=MessageType.ERROR, message=error_msg)

def make_chat_packet(sender: str, text: str) -> Packet:
    return Packet(type=MessageType.CHAT, sender=sender, text=text)