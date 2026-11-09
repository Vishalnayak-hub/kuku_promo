"""Candidate generation.

v1 slid a fixed window over the timeline every 5 s, so cuts landed mid-sentence
and nothing guaranteed a hook or a clean ending. Here a candidate is built from
*beats*:

* it opens on the first frame of a shot whose dialogue/action begins within
  ``HOOK_WINDOW`` seconds (so "something happens in the first 3 s" holds by
  construction, not by luck);
* it closes on the last frame of a shot, after a finished line/action/sound;
* it never cuts through a spoken line, and never splits a sentence that the
  script itself continues in the next line ("...search." / "...let the constable").
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from .models import ACTION, DIALOGUE, SOUND_FX, Episode, Event

HOOK_WINDOW = 3.0  # brief: the hook must land in the first 3 seconds
SNAP_LIMIT = 2.5  # max distance we will move a cut to reach a shot boundary
CLOSING_SHOT_LIMIT = 8.0  # max silent tail we will include to reach the episode end
FINAL_HOLD_MAX = 8.0  # seconds of silent closing shots we may include at an episode end
MIN_DIALOGUE_LINES = 3
MIN_SPOKEN_RATIO = 0.25  # at least 25 % of the clip must be speech
_TRAIL = ("...", "\u2026", "\u2014", "--", "-")
_LEAD = ("...", "\u2026", "\u2014", "--")


@dataclass
class Candidate:
    episode: int
    start: float  # cut-in  (seconds from episode start)
    end: float  # cut-out
    opener: Event  # first dialogue/action inside the clip
    closer: Event  # last dialogue/action/sound inside the clip

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def key(self) -> tuple[int, float, float]:
        return (self.episode, round(self.start, 2), round(self.end, 2))


class EpisodeIndex:
    """Pre-computed lookups so scoring thousands of windows stays fast."""

    def __init__(self, ep: Episode):
        self.ep = ep
        self.dialogue = sorted(ep.dialogue, key=lambda e: (e.start, e.end))
        self.d_starts = [d.start for d in self.dialogue]
        self.cams = sorted(ep.camera, key=lambda e: e.start)
        self.beats = sorted((e for e in ep.events if e.kind in (DIALOGUE, ACTION, SOUND_FX)),
                            key=lambda e: (e.start, e.end))
        self.actions = [e for e in self.beats if e.kind in (ACTION, SOUND_FX)]
        self.duration = ep.duration
        self._cont_next = [False] * len(self.dialogue)
        self._cont_prev = [False] * len(self.dialogue)
        for i in range(len(self.dialogue) - 1):
            a, b = self.dialogue[i], self.dialogue[i + 1]
            same = a.who == b.who and b.start - a.end <= 1.5
            if same and (a.text.rstrip().endswith(_TRAIL) or b.text.lstrip().startswith(_LEAD)):
                self._cont_next[i] = True
                self._cont_prev[i + 1] = True
        self._dpos = {d.idx: i for i, d in enumerate(self.dialogue)}

    # -- helpers ---------------------------------------------------------
    def lines_between(self, start: float, end: float) -> list[Event]:
        lo = bisect_left(self.d_starts, start - 0.02)
        out = []
        for d in self.dialogue[lo:]:
            if d.start >= end - 0.02:
                break
            if d.end <= end + 0.02:
                out.append(d)
        return out

    def line_before(self, t: float) -> Event | None:
        """Last dialogue line that finished at or before t."""
        best = None
        for d in self.dialogue:
            if d.end <= t + 0.02:
                best = d
            elif d.start > t:
                break
        return best

    def line_after(self, t: float) -> Event | None:
        """First dialogue line starting at or after t."""
        i = bisect_left(self.d_starts, t - 0.02)
        return self.dialogue[i] if i < len(self.dialogue) else None

    def straddles(self, t: float) -> bool:
        """True if a cut at time t would slice through a spoken line, or
        through an action/sound that still has more than ~1 s left to run."""
        i = bisect_right(self.d_starts, t - 0.02)
        for d in self.dialogue[max(0, i - 6):i]:
            if d.start < t - 0.02 and d.end > t + 0.02:
                return True
        for a in self.actions:
            if a.start < t - 0.3 and a.end > t + 1.0:
                return True
        return False

    def other_beat_starts(self, lo: float, hi: float, exclude: Event) -> bool:
        """Does any dialogue/action/sound begin inside (lo, hi) besides ``exclude``?"""
        return any(b is not exclude and lo - 0.02 <= b.start < hi - 0.1 for b in self.beats)

    def continues_next(self, d: Event) -> bool:
        return self._cont_next[self._dpos[d.idx]]

    def continues_prev(self, d: Event) -> bool:
        return self._cont_prev[self._dpos[d.idx]]

    def snap_start(self, t: float) -> float:
        for c in self.cams:
            if c.start <= t + 0.01 < c.end:
                return c.start if t - c.start <= SNAP_LIMIT else t
            if c.start > t:
                break
        return t

    def snap_end(self, t: float) -> float:
        for c in self.cams:
            if c.start < t - 0.01 <= c.end + 0.01:
                if abs(c.end - t) < 0.02:
                    return c.end
                return c.end if c.end - t <= SNAP_LIMIT else t
            if c.start >= t:
                break
        return t


def _is_valid_opener(ix: EpisodeIndex, e: Event) -> bool:
    if e.kind == DIALOGUE:
        return not e.voiceover and not ix.continues_prev(e)
    return e.kind == ACTION


def _is_valid_closer(ix: EpisodeIndex, e: Event) -> bool:
    if e.kind == DIALOGUE:
        return not ix.continues_next(e)
    return e.kind in (ACTION, SOUND_FX)


def generate(ep: Episode, min_s: float = 20.0, max_s: float = 60.0,
             ix: EpisodeIndex | None = None, min_lines: int = MIN_DIALOGUE_LINES) -> list[Candidate]:
    """All clean-cut windows of ``min_s``-``max_s`` seconds in one episode."""
    ix = ix or EpisodeIndex(ep)
    beats = [e for e in ep.events if e.kind in (DIALOGUE, ACTION, SOUND_FX)]
    openers = [e for e in beats if _is_valid_opener(ix, e)]
    closers = [e for e in beats if _is_valid_closer(ix, e)]

    last_beat_end = max((b.end for b in beats), default=0.0)
    seen: dict[tuple, Candidate] = {}
    for o in openers:
        s_raw = o.start
        s_snapped = ix.snap_start(s_raw)
        for s in ((s_snapped, s_raw) if s_snapped != s_raw else (s_raw,)):
            if ix.straddles(s) or o.start - s > HOOK_WINDOW:
                continue
            for c in closers:
                if c.end <= o.start:
                    continue
                snapped = ix.snap_end(c.end)
                variants = {c.end}
                if snapped != c.end and not ix.other_beat_starts(c.end, snapped, c):
                    variants.add(snapped)
                # nothing but a silent closing shot is left: the episode's own last
                # frame (usually a reaction hold) is the natural cliffhanger cut
                if c.end >= last_beat_end - 0.02 and 0 < ix.duration - c.end <= CLOSING_SHOT_LIMIT:
                    variants.add(ix.duration)
                # Final beat of the episode followed only by silent camera holds: the show's own
                # closing image is part of the cliffhanger, so allow the cut to reach the true end.
                if (ix.duration - c.end <= FINAL_HOLD_MAX and ix.duration - c.end > 0.02
                        and not ix.other_beat_starts(c.end, ix.duration + 1.0, c)):
                    variants.add(ix.duration)
                for e_t in sorted(variants):
                    dur = e_t - s
                    if dur < min_s - 1e-6 or dur > max_s + 1e-6:
                        continue
                    if ix.straddles(e_t) or e_t > ix.duration + 0.5:
                        continue
                    cand = Candidate(ep.number, round(s, 2), round(e_t, 2), o, c)
                    if cand.key in seen:
                        continue
                    lines = ix.lines_between(cand.start, cand.end)
                    if len(lines) < min_lines:
                        continue
                    spoken = sum(min(d.end, cand.end) - max(d.start, cand.start) for d in lines)
                    if spoken / dur < MIN_SPOKEN_RATIO:
                        continue
                    seen[cand.key] = cand
    return sorted(seen.values(), key=lambda c: (c.start, c.end))
