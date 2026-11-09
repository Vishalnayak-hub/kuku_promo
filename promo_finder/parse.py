"""Screenplay parser.

Reads the Kuku screenplay format (timestamped CAMERA / ACTION / SOUND FX /
dialogue blocks grouped in scenes) and is deliberately tolerant, because the
pipeline has to run on a show it has never seen:

* one broken file never aborts the run - it is reported and skipped;
* odd timestamp styles, missing scene markers, CRLF, BOM, extra labels are fine;
* every anomaly is recorded in ``Episode.warnings`` and in the parse report
  instead of being silently "fixed".
"""
from __future__ import annotations

import io
import re
import tempfile
import zipfile
from pathlib import Path

from .models import ACTION, CAMERA, DIALOGUE, SOUND_FX, Episode, Event, Scene

_TS = r"(?:(\d+):)?(\d{1,2}):(\d{2}(?:\.\d+)?)"  # [h:]mm:ss[.xx]
TS_RE = re.compile(_TS)
HEADER_RE = re.compile(r"^\*\*(?P<inner>.+?)\*\*\s*$")
TIMING_RE = re.compile(
    rf"^Start:\s*\(?\s*(?P<s>{_TS})\s*\)?\s*\|\s*End:\s*\(?\s*(?P<e>{_TS})\s*\)?",
    re.IGNORECASE,
)
SCENE_RE = re.compile(r"^SCENE\s+(?P<n>\d+)\s*$", re.IGNORECASE)
END_MARKERS = ("--- SCRIPT END ---",)

_SOUND_LABELS = {
    "SOUND FX", "SOUND_FX", "SOUNDFX", "SFX", "SOUND EFFECT", "SOUND EFFECTS",
    "SOUND", "MUSIC", "SCORE",
}
_VOICEOVER = {"v.o.", "vo", "v.o", "voice over", "voice-over"}
_OFFSCREEN = {"o.s.", "os", "o.s", "o.c.", "oc", "off screen", "off-screen"}
_HONORIFICS = {"LADY", "SIR", "DOWAGER", "FATHER", "YOUNG", "OLD", "MISS", "MRS", "MR", "DR"}

#: A scene boundary may be overshot by a fraction of a second in the source
#: (the pack has one 0.3 s case). Report it, but only above this tolerance.
SCENE_OVERSHOOT_TOLERANCE = 0.05


def parse_ts(value: str) -> float:
    """'01:23.45' / '1:02:03.5' / '00:07' -> seconds."""
    m = TS_RE.fullmatch(value.strip().strip("()"))
    if not m:
        raise ValueError(f"bad timestamp: {value!r}")
    hours, minutes, seconds = m.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + float(seconds)


def _speaker_key(label: str) -> str:
    tokens = label.split()
    while len(tokens) > 1 and tokens[0] in _HONORIFICS:
        tokens = tokens[1:]
    return " ".join(tokens)


def _clean_quotes(text: str) -> str:
    text = " ".join(text.split())
    for left, right in (('"', '"'), ("\u201c", "\u201d"), ("'", "'")):
        if len(text) >= 2 and text[0] == left and text[-1] == right:
            return text[1:-1].strip()
    return text


def _classify(inner: str):
    """'LADY JULIANA (Confused, Breathless):' -> kind, speaker, tags, vo, os."""
    groups = re.findall(r"\(([^)]*)\)", inner)
    base = re.sub(r"\s*\([^)]*\)", "", inner).strip().rstrip(":").strip().upper()
    if base == "CAMERA":
        return CAMERA, None, (), False, False
    if base == "ACTION":
        return ACTION, None, (), False, False
    if base in _SOUND_LABELS:
        return SOUND_FX, None, (), False, False
    tags, vo, off = [], False, False
    for group in groups:
        for piece in group.split(","):
            piece = piece.strip().lower()
            if not piece:
                continue
            if piece in _VOICEOVER:
                vo = True
            elif piece in _OFFSCREEN:
                off = True
            else:
                tags.append(piece)
    return DIALOGUE, base, tuple(tags), vo, off


def _episode_number(text: str, filename: str) -> int | None:
    m = re.search(r"(?im)^EPISODE NUMBER:\s*(?:Episode\s*)?(\d+)", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(?i)episode[-_ ]*0*(\d+)", filename) or re.search(r"(\d+)", filename)
    return int(m.group(1)) if m else None


def parse_text(text: str, filename: str = "episode.txt") -> Episode:
    """Parse one screenplay. Raises ValueError if it contains no timed blocks."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").split("\n")

    number = _episode_number(text, filename)
    logline = (re.search(r"(?im)^EPISODE LOGLINE:\s*(.*)$", text) or [None, ""])[1].strip()
    continuity = (re.search(r"(?im)^CONTINUITY NOTES:\s*(.*)$", text) or [None, ""])[1].strip()
    ep = Episode(number=number if number is not None else -1, source=filename,
                 logline=logline, continuity=continuity)

    scene_no, heading = 1, ""
    scene_bounds: dict[int, list] = {}  # n -> [heading, start, end]
    events: list[Event] = []

    def ensure_scene(n):
        scene_bounds.setdefault(n, ["", None, None])
        return scene_bounds[n]

    ensure_scene(1)
    i, n_lines = 0, len(lines)
    while i < n_lines:
        raw = lines[i].strip()
        m_scene = SCENE_RE.match(raw)
        if m_scene:
            scene_no = int(m_scene.group("n"))
            heading = ""
            ensure_scene(scene_no)
            i += 1
            continue
        low = raw.lower()
        if low.startswith("scene heading:"):
            ensure_scene(scene_no)[0] = raw.split(":", 1)[1].strip()
        elif low.startswith("scene start:"):
            try:
                ensure_scene(scene_no)[1] = parse_ts(raw.split(":", 1)[1].strip())
            except ValueError:
                ep.warnings.append(f"scene {scene_no}: unreadable scene start")
        elif low.startswith("scene end:"):
            try:
                ensure_scene(scene_no)[2] = parse_ts(raw.split(":", 1)[1].strip())
            except ValueError:
                ep.warnings.append(f"scene {scene_no}: unreadable scene end")
        m_head = HEADER_RE.match(raw)
        if m_head:
            # next non-empty line must be the timing line
            j = i + 1
            while j < n_lines and not lines[j].strip():
                j += 1
            m_time = TIMING_RE.match(lines[j].strip()) if j < n_lines else None
            if not m_time:
                ep.warnings.append(f"line {i + 1}: header {raw!r} has no Start/End line - skipped")
                i += 1
                continue
            start, end = parse_ts(m_time.group("s")), parse_ts(m_time.group("e"))
            k = j + 1
            body: list[str] = []
            while k < n_lines:
                nxt = lines[k].strip()
                if HEADER_RE.match(nxt) or SCENE_RE.match(nxt) or nxt in END_MARKERS:
                    break
                if nxt.lower().startswith("actions and dialogue"):
                    break
                body.append(nxt)
                k += 1
            kind, speaker, tags, vo, off = _classify(m_head.group("inner"))
            content = _clean_quotes(" ".join(b for b in body if b))
            if end <= start:
                ep.warnings.append(
                    f"scene {scene_no} {kind} at {start:.2f}: non-positive duration - skipped")
            elif not content:
                ep.warnings.append(f"scene {scene_no} {kind} at {start:.2f}: empty text - skipped")
            else:
                events.append(Event(
                    idx=len(events), kind=kind, start=start, end=end, text=content,
                    scene=scene_no, speaker=speaker,
                    who=_speaker_key(speaker) if speaker else None,
                    tags=tags, voiceover=vo, offscreen=off))
            i = k
            continue
        i += 1

    if not events:
        raise ValueError("no timed blocks found (is this a screenplay file?)")

    events.sort(key=lambda e: (e.start, e.end, e.idx))
    for new_idx, e in enumerate(events):
        e.idx = new_idx

    # scenes: fill missing bounds from the events, flag overshoots (never "fix" them)
    for n, (head, s, e_) in sorted(scene_bounds.items()):
        inside = [ev for ev in events if ev.scene == n]
        if not inside and s is None and e_ is None:
            continue
        if s is None:
            s = min(ev.start for ev in inside)
            ep.warnings.append(f"scene {n}: start inferred from events")
        if e_ is None:
            e_ = max(ev.end for ev in inside)
            ep.warnings.append(f"scene {n}: end inferred from events")
        ep.scenes.append(Scene(n, head, s, e_))
        over = [ev for ev in inside if ev.end > e_ + SCENE_OVERSHOOT_TOLERANCE]
        for ev in over:
            ep.warnings.append(
                f"scene {n}: {ev.kind} ends {ev.end - e_:.2f}s after scene end (kept as in source)")
    ep.events = events
    if not any(e.kind == DIALOGUE for e in events):
        ep.warnings.append("episode has no dialogue")
    return ep


def _iter_files(path: Path):
    if path.is_file():
        yield path
        return
    for p in sorted(path.rglob("*.txt")):
        if not any(part.startswith(".") for part in p.relative_to(path).parts):
            yield p


def load_inputs(path: str | Path) -> tuple[list[Episode], list[dict]]:
    """Load every screenplay under ``path`` (dir, single .txt, or .zip).

    Returns (episodes sorted by number, report rows). Never raises for a single
    bad file; raises FileNotFoundError only if ``path`` does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"input path not found: {path}")
    if path.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="promo_input_"))
        with zipfile.ZipFile(path) as zf:
            # ZipFile.extractall already drops absolute paths and '..' parts,
            # so members cannot escape ``tmp``.
            zf.extractall(tmp)
        return load_inputs(tmp)

    episodes: list[Episode] = []
    report: list[dict] = []
    seen: dict[int, str] = {}
    for f in _iter_files(path):
        row = {"file": f.name, "status": "ok", "episode": "", "events": 0, "warnings": ""}
        try:
            ep = parse_text(f.read_text(encoding="utf-8-sig", errors="replace"), f.name)
            if ep.number in seen:
                row["status"] = "skipped"
                row["warnings"] = f"duplicate episode number {ep.number} (already loaded from {seen[ep.number]})"
            else:
                if ep.number == -1:
                    ep.number = 1000 + len(episodes)
                    ep.warnings.append("episode number not found - assigned placeholder")
                seen[ep.number] = f.name
                episodes.append(ep)
                row.update(episode=ep.number, events=len(ep.events),
                           warnings=" | ".join(ep.warnings))
                if ep.warnings:
                    row["status"] = "ok_with_warnings"
        except Exception as exc:  # report and continue
            row["status"] = "error"
            row["warnings"] = f"{type(exc).__name__}: {exc}"
        report.append(row)
    episodes.sort(key=lambda e: e.number)
    return episodes, report


def load_uploaded(files: list[tuple[str, bytes]]) -> tuple[list[Episode], list[dict]]:
    """Used by the web app: [(filename, bytes), ...] -> episodes."""
    tmp = Path(tempfile.mkdtemp(prefix="promo_upload_"))
    for name, data in files:
        safe = Path(name).name
        if safe.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(tmp)
        else:
            (tmp / safe).write_bytes(data)
    return load_inputs(tmp)
