"""
audio.py - Robust audio playback module for CLI applications.
Features:
- Segment playback (start timestamp, end timestamp, duration limits)
- Immediate audio stopping/cutting
- Thread-safe non-blocking & blocking execution
- Comprehensive error handling for missing hardware, invalid files, and bad timestamps
"""

import os
import time
import threading
from typing import Union, Optional
from pathlib import Path

try:
    import pygame
except ImportError:
    raise ImportError(
        "The 'pygame' library is required. Please install it using: pip install pygame"
    )


class AudioPlayer:
    """Thread-safe audio player supporting partial playback and instant cutoffs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_playing = False
        self._last_error: Optional[Exception] = None

    def _ensure_mixer_initialized(self):
        """Initializes the pygame mixer if not already initialized."""
        if not pygame.mixer.get_init():
            try:
                pygame.mixer.init()
            except pygame.error as e:
                raise RuntimeError(
                    f"Failed to initialize audio hardware/mixer: {e}"
                ) from e

    def play(
        self,
        file_path: Union[str, Path],
        start_sec: float = 0.0,
        end_sec: Optional[float] = None,
        duration_sec: Optional[float] = None,
        blocking: bool = False,
    ):
        """
        Play a segment of an audio file.

        :param file_path: Path to audio file (.mp3, .wav, .ogg, etc.)
        :param start_sec: Start offset in seconds (>= 0.0)
        :param end_sec: Audio timestamp where playback should end (must be > start_sec)
        :param duration_sec: Max playback duration in seconds
        :param blocking: If True, blocks until playback finishes or is stopped.
        """
        path_obj = Path(file_path)

        # 1. Early Synchronous Validations (Fail-Fast on Main Thread)
        if not path_obj.exists():
            raise FileNotFoundError(f"Audio file not found: '{path_obj.resolve()}'")
        if not path_obj.is_file():
            raise ValueError(f"Path is not a valid file: '{path_obj.resolve()}'")
        if start_sec < 0:
            raise ValueError("start_sec cannot be negative")

        calc_duration = None
        if end_sec is not None:
            if end_sec < start_sec:
                raise ValueError("end_sec must be greater than or equal to start_sec")
            calc_duration = float(end_sec) - float(start_sec)

        if duration_sec is not None:
            if duration_sec < 0:
                raise ValueError("duration_sec cannot be negative")
            dur = float(duration_sec)
            calc_duration = dur if calc_duration is None else min(calc_duration, dur)

        # 2. Stop any existing playback clean
        self.stop()

        # 3. Initialize background thread
        with self._lock:
            self._ensure_mixer_initialized()
            self._last_error = None
            self._stop_event.clear()
            self._is_playing = True

            self._thread = threading.Thread(
                target=self._play_worker,
                args=(str(path_obj.resolve()), float(start_sec), calc_duration),
                daemon=True,
            )
            self._thread.start()

        if blocking:
            self.wait()

    def _play_worker(
        self, file_path: str, start_sec: float, duration_sec: Optional[float]
    ):
        """Worker function running in a separate thread."""
        try:
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play(loops=0, start=start_sec)

            start_time = time.monotonic()

            while not self._stop_event.is_set():
                if not pygame.mixer.music.get_busy():
                    break  # Audio finished playing naturally

                if duration_sec is not None:
                    elapsed = time.monotonic() - start_time
                    if elapsed >= duration_sec:
                        break  # Duration limit reached

                time.sleep(0.04)  # ~25 FPS polling loop, low CPU overhead

        except Exception as e:
            with self._lock:
                self._last_error = e
        finally:
            # Clean up audio playback hardware/buffers
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.music.stop()
                    if hasattr(pygame.mixer.music, "unload"):
                        pygame.mixer.music.unload()
            except Exception:
                pass

            with self._lock:
                self._is_playing = False

    def stop(self):
        """Instantly stop audio playback."""
        with self._lock:
            thread = self._thread
            self._stop_event.set()

        # Join outside lock to prevent deadlocks
        if thread and thread.is_alive() and thread != threading.current_thread():
            thread.join(timeout=2.0)

        with self._lock:
            self._is_playing = False

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        with self._lock:
            return self._is_playing

    def get_last_error(self) -> Optional[Exception]:
        """Return the error exception if worker thread crashed during playback."""
        with self._lock:
            return self._last_error

    def wait(self):
        """
        Block caller thread until playback finishes.
        Raises any exception encountered during background playback.
        """
        thread = None
        with self._lock:
            thread = self._thread

        if thread and thread.is_alive() and thread != threading.current_thread():
            thread.join()

        # Re-raise worker thread errors on caller thread
        with self._lock:
            if self._last_error:
                err = self._last_error
                self._last_error = None
                raise RuntimeError(
                    f"Audio playback error: {err}"
                ) from err


# Global instance for standard functional imports
_default_player = AudioPlayer()


def play_audio(
    file_path: Union[str, Path],
    start_sec: float = 0.0,
    end_sec: Optional[float] = None,
    duration_sec: Optional[float] = None,
    blocking: bool = False,
):
    """Play an audio file segment."""
    _default_player.play(file_path, start_sec, end_sec, duration_sec, blocking)


def stop_audio():
    """Instantly stop audio playback."""
    _default_player.stop()


def is_playing() -> bool:
    """Check if audio is currently playing."""
    return _default_player.is_playing()


def wait_audio():
    """Wait for current playback to complete and re-raise any worker errors."""
    _default_player.wait()


def get_last_error() -> Optional[Exception]:
    """Retrieve any worker thread error."""
    return _default_player.get_last_error()




