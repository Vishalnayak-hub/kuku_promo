"""Data model shared by every stage of the pipeline.

Pure standard library on purpose: the engine must install and run anywhere
(a laptop, Colab, an interview machine) with nothing but Python 3.10+.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DIALOGUE = "DIALOGUE"
ACTION = "ACTION"
CAMERA = "CAMERA"
SOUND_FX = "SOUND_FX"


@dataclass
class Event:
    """One timestamped block of the screenplay."""

    idx: int
    kind: str  # DIALOGUE | ACTION | CAMERA | SOUND_FX
    start: float
    end: float
    text: str
    scene: int = 1
    speaker: str | None = None  # raw label, e.g. "LADY JULIANA"
    who: str | None = None  # normalised key used to count distinct speakers
    tags: tuple[str, ...] = ()  # delivery cues, lower-case, e.g. ("cold", "certain")
    voiceover: bool = False  # (V.O.) inner monologue / narration
    offscreen: bool = False  # (O.S.)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Scene:
    number: int
    heading: str
    start: float
    end: float


@dataclass
class Episode:
    number: int
    source: str
    logline: str = ""
    continuity: str = ""
    scenes: list[Scene] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        ends = [s.end for s in self.scenes] + [e.end for e in self.events]
        return max(ends) if ends else 0.0

    @property
    def dialogue(self) -> list[Event]:
        return [e for e in self.events if e.kind == DIALOGUE]

    @property
    def camera(self) -> list[Event]:
        return [e for e in self.events if e.kind == CAMERA]


@dataclass
class Segment:
    """One continuous stretch of one episode (seconds)."""

    episode: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def fmt_ts(seconds: float) -> str:
    """Seconds -> 'mm:ss.xx' (the format used in the input pack)."""
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    # guard against 59.999 rounding up to 60.00
    if round(rest, 2) >= 60.0:
        minutes += 1
        rest = 0.0
    return f"{minutes:02d}:{rest:05.2f}"
