"""Heuristic judge: scores one candidate window against the brief's three tests.

    hook        something in the first 3 s makes a scrolling viewer stop
    cliffhanger it cuts at an unresolved moment
    standalone  it makes sense to someone who has never seen the show

plus ``tension`` (is it a confrontation that escalates?) and ``pace`` (no dead
air, sensible length). Weights sum to 100.

This is a *screening* judge: free, offline, deterministic and explainable. It
cannot understand a story - that is what the optional LLM judge is for. Every
sub-score is returned so a human can see *why* a window ranked where it did.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import textcues as tc
from .candidates import Candidate, EpisodeIndex
from .models import ACTION, DIALOGUE, SOUND_FX, Event

WEIGHTS = {"hook": 25, "cliffhanger": 30, "standalone": 15, "tension": 20, "pace": 10}
HOOK_WINDOW = 3.0
#: Microdrama episodes end on the writer's own cliffhanger (41/49 next-episode notes open with a
#: continuation phrase; 11 describe the cliffhanger outright). Raised 7 -> 12 after the first evaluation
#: showed the scorer ignored it - so cliffhanger-note results after this change are in-sample.
EPISODE_END_BONUS = 12


@dataclass
class LineInfo:
    intensity: float
    question: bool
    interrupted: bool
    words: int
    conflict_hits: int
    reveal: bool
    ultimatum: bool
    closure: bool
    imperative: bool
    weak_opener: bool
    discourse_opener: bool
    pronoun_opener: bool
    addresses_you: bool

    @classmethod
    def of(cls, d: Event) -> "LineInfo":
        t = d.text
        return cls(
            intensity=tc.line_intensity(d),
            question=tc.ends_with_question(t),
            interrupted=tc.ends_interrupted(t),
            words=tc.word_count(t),
            conflict_hits=len(tc.CONFLICT.findall(t)),
            reveal=bool(tc.REVEAL.search(t)),
            ultimatum=bool(tc.ULTIMATUM.search(t)),
            closure=tc.has_closure(t),
            imperative=bool(tc.IMPERATIVE.search(t)),
            weak_opener=bool(tc.WEAK_OPENER.search(t)),
            discourse_opener=bool(tc.DISCOURSE_OPENER.search(t)),
            pronoun_opener=bool(tc.PRONOUN_OPENER.search(t)),
            addresses_you=bool(re.search(r"\byou(?:r|'re|'ve|'ll)?\b", t, re.I)),
        )


@dataclass
class Scored:
    cand: Candidate
    total: float
    parts: dict[str, float]
    flags: list[str] = field(default_factory=list)
    hook_label: str = ""
    cliff_label: str = ""
    hook_line: str = ""
    cliff_line: str = ""
    withheld: str = ""  # the line that comes right after the cut
    why: str = ""
    n_lines: int = 0
    n_speakers: int = 0
    judge: str = "heuristic"
    llm: dict | None = None
    extra: list[Candidate] = field(default_factory=list)  # further segments, in order (stitched promos)
    stitched: bool = False


def _info(ix: EpisodeIndex) -> dict[int, LineInfo]:
    cache = getattr(ix, "_info", None)
    if cache is None:
        cache = {d.idx: LineInfo.of(d) for d in ix.dialogue}
        ix._info = cache
    return cache


def _spk(d: Event) -> str:
    return d.who or d.speaker or "?"


def _pretty(e: Event) -> str:
    tag = f" ({', '.join(e.tags[:2])})" if e.tags else ""
    return f"{_spk(e)}{tag}: \u201c{e.text}\u201d"


def _hook(ix, info, cand, lines):
    o = cand.opener
    pts, label = 0.0, ""
    flags = []
    if o.kind == DIALOGUE:
        li = info[o.idx]
        pts += 8 * li.intensity
        shape = 0
        if li.imperative:
            shape, label = 5, "a command"
        elif li.ultimatum:
            shape, label = 5, "an ultimatum"
        elif li.question:
            shape, label = 4, "a pointed question"
        elif "!" in o.text:
            shape, label = 3, "an exclamation"
        pts += shape
        if li.words <= 10:
            pts += 3
        elif li.words <= 16:
            pts += 1.5
        if li.addresses_you:
            pts += 2
        if li.reveal:
            pts += 3
            label = (label + " / " if label else "") + "a reveal"
        if li.weak_opener:
            pts -= 6
            flags.append("weak opener (pleasantry)")
        elif li.discourse_opener:
            pts -= 2
        if o.voiceover:
            pts -= 3
        # an instant reply from someone else = a fight, not a speech
        reply = [d for d in lines if d is not o and d.start <= cand.start + HOOK_WINDOW
                 and _spk(d) != _spk(o)]
        if reply:
            pts += 2
            label = (label + ", " if label else "") + "instant back-and-forth"
        mood = f"{_spk(o)}, {o.tags[0]}" if o.tags else _spk(o)
        label = f"{label or 'a line'} ({mood})"
        line = _pretty(o)
    else:
        if tc.IMPACT_ACTION.search(o.text):
            pts += 16
            verb = tc.IMPACT_ACTION.search(o.text).group(0).lower().split()[0]
            label = f"a physical action ({verb})"
        else:
            pts += 3
            label = "a quiet action beat"
        line = f"[ACTION] {o.text}"
    return max(0.0, min(25.0, pts)), label, line, flags


def _cliff(ix, info, cand, lines, mean_int):
    """
    Score the ending by distinguishing intentional dramatic
    interruptions from accidental dialogue cuts.
    """
    c = cand.closer
    last_line = lines[-1] if lines else None

    pts = 0.0
    signals = []
    flags = []

    withheld = ix.line_after(cand.end)
    withheld_txt = ""
    cliff_line = ""

    if last_line is not None:
        li = info[last_line.idx]
        near = cand.end - last_line.end <= 3.0

        cliff_line = _pretty(last_line)

        # Check whether a dramatic action follows the interrupted dialogue.
        reaction_after = any(
            e.kind in (ACTION, SOUND_FX)
            and e.start <= last_line.end + 0.5
            and e.end >= last_line.end - 0.3
            and e.start < cand.end
            and tc.SUDDEN_END.search(e.text)
            for e in ix.ep.events
        )

        # Check whether the same speaker immediately continues
        # the interrupted sentence outside the selected promo.
        same_speaker_continues = bool(
            li.interrupted
            and withheld is not None
            and _spk(withheld) == _spk(last_line)
            and withheld.start - last_line.end <= 3.0
        )

        # 1. Interrupted dialogue evaluation
        if near and li.interrupted:

            if same_speaker_continues:
                pts -= 8
                flags.append(
                    "likely accidental cut "
                    "(same speaker continues immediately after)"
                )

            elif reaction_after:
                pts += 8
                signals.append(
                    "cuts off mid-sentence; interrupted revelation "
                    "followed by a dramatic reaction"
                )

            elif (
                withheld is not None
                and _spk(withheld) != _spk(last_line)
            ):
                pts += 6
                signals.append(
                    "interrupted line invites an immediate response"
                )

            elif cand.end >= ix.duration - 1.0:
                pts += 6
                signals.append(
                    "cuts off mid-sentence; episode-ending "
                    "interrupted revelation"
                )

            else:
                pts += 2
                signals.append(
                    "interrupted line "
                    "(intent not independently confirmed)"
                )

        # 2. Unanswered questions
        if near and li.question:
            pts += 8
            signals.append("ends on an unanswered question")

            if (
                withheld is not None
                and _spk(withheld) != _spk(last_line)
            ):
                pts += 3

        # 3. Threats and ultimatums
        if near and li.ultimatum:
            pts += 5
            signals.append("ends on a threat/ultimatum")

        # 4. Short, emotionally charged dialogue
        if near and li.words <= 7 and li.intensity >= 0.6:
            pts += 4
            signals.append("lands on a short, charged line")

        # 5. Important revelation
        if near and li.reveal:
            pts += 4
            signals.append("lands on a reveal")

        # 6. Emotional intensity
        if near and li.intensity >= mean_int + 0.1:
            pts += 2

        # 7. Penalize endings that resolve the conflict
        if li.closure:
            pts -= 10
            flags.append("ends on resolution (closure phrase)")

        # 8. Penalize clips that include both a question and its answer
        if len(lines) >= 2:
            prev = lines[-2]
            pi = info[prev.idx]

            if (
                pi.question
                and _spk(prev) != _spk(last_line)
                and not li.question
                and not li.interrupted
            ):
                pts -= 6
                flags.append(
                    "ends on an answer "
                    "(question resolved inside the clip)"
                )

        # 9. Penalize long, non-interrogative endings
        if li.words >= 18 and not li.question and not li.interrupted:
            pts -= 3

    # 10. Dramatic action or sound at the ending
    if (
        c.kind in (ACTION, SOUND_FX)
        and cand.end - c.end <= 2.6
        and (
            tc.SUDDEN_END.search(c.text)
            or tc.IMPACT_ACTION.search(c.text)
        )
    ):
        pts += 8
        signals.append("ends on a sudden sound/arrival/impact")

        cliff_line = (
            f"[{c.kind}] {c.text}"
            if not cliff_line
            else cliff_line + f"  → [{c.kind}] {c.text}"
        )

    # 11. Visual reveal
    elif any(
        cm.end > cand.end - 3.0
        and cm.start < cand.end
        and tc.VISUAL_REVEAL.search(cm.text)
        for cm in ix.cams
    ):
        pts += 5
        signals.append("ends on a visual reveal")

    # 12. Episode-ending bonus
    if cand.end >= ix.duration - 1.0:
        pts += EPISODE_END_BONUS
        signals.append("ends where the episode itself ends")

    if withheld is not None:
        withheld_txt = _pretty(withheld)

    if not signals:
        flags.append("no cliffhanger signal")

    return (
        max(0.0, min(30.0, pts)),
        signals,
        cliff_line,
        withheld_txt,
        flags,
    )

def _standalone(ix, info, cand, lines):
    """
    Evaluate whether a promo makes sense to a viewer
    who has not watched the previous episodes.
    """
    o = cand.opener
    pts = 4.0
    flags = []

    prev = ix.line_before(cand.start)
    gap = cand.start - (prev.end if prev else 0.0)

    # 1. Reward a natural scene or conversation opening.
    if prev is None or gap >= 2.0 or prev.scene != o.scene:
        pts += 4

    # 2. Detect openings that depend on unseen dialogue.
    if (
        o.kind == DIALOGUE
        and prev is not None
        and gap < 2.0
        and prev.scene == o.scene
    ):
        pi = info[prev.idx]
        oi = info[o.idx]

        # A reply to an unseen question is a strong context problem.
        if (
            pi.question
            and _spk(prev) != _spk(o)
            and not oi.question
        ):
            pts -= 5
            flags.append(
                "starts mid-exchange "
                "(answers a question the viewer never saw)"
            )

        # Explicit context-dependent opening phrases.
        elif tc.CONTEXT_DEPENDENT_OPENER.search(o.text):
            pts -= 3
            flags.append(
                "context-dependent opener "
                "(refers to an earlier conversation)"
            )

        # Pronoun or conjunction openings.
        elif oi.pronoun_opener or oi.discourse_opener:
            pts -= 2
            flags.append(
                "opens mid-conversation "
                "(pronoun/conjunction opener)"
            )

    # 3. Evaluate character balance.
    speakers = {
        _spk(d)
        for d in lines
        if not d.voiceover
    }

    k = len(speakers)

    if k in (2, 3):
        pts += 4
    elif k == 4:
        pts += 2
    elif k <= 1:
        pts -= 3
        flags.append("monologue (one speaker)")
    else:
        pts -= 2
        flags.append("crowded (5+ speakers)")

    # 4. Reward character identification through dialogue.
    named = 0

    for speaker in speakers:
        first = speaker.split()[-1]

        if len(first) >= 3 and any(
            _spk(d) != speaker
            and re.search(
                rf"\b{re.escape(first)}\b",
                d.text,
                re.I
            )
            for d in lines
        ):
            named += 1

    pts += min(3, named)

    return max(0.0, min(15.0, pts)), flags, k


def _tension(info, lines):
    if not lines:
        return 0.0, 0
    ints = [info[d.idx].intensity for d in lines]
    pts = 8 * (sum(ints) / len(ints))
    changes = sum(1 for a, b in zip(lines, lines[1:]) if _spk(a) != _spk(b))
    pts += min(4.0, changes / 2)
    third = max(1, len(ints) // 3)
    diff = sum(ints[-third:]) / third - sum(ints[:third]) / third
    pts += min(4.0, max(0.0, diff) * 10)
    pts += min(4, sum(info[d.idx].conflict_hits for d in lines))
    return max(0.0, min(20.0, pts)), changes


def _pace(cand, lines):
    dur = cand.duration
    spoken = sum(min(d.end, cand.end) - max(d.start, cand.start) for d in lines)
    ratio = spoken / dur if dur else 0.0
    pts = 4.0 if ratio >= 0.55 else max(0.0, 4.0 * (ratio - 0.25) / 0.30)
    # silent gaps: between consecutive lines, plus lead-in and tail
    edges = [(cand.start, lines[0].start)] if lines else []
    edges += [(a.end, b.start) for a, b in zip(lines, lines[1:])]
    edges += [(lines[-1].end, cand.end)] if lines else []
    max_gap = max((b - a for a, b in edges), default=0.0)
    flags = []
    pts += 3.0 if max_gap <= 4 else (1.5 if max_gap <= 7 else 0.0)
    if max_gap > 8:
        flags.append(f"long silence ({max_gap:.0f}s without speech)")
    if 28 <= dur <= 52:
        pts += 3
    elif 22 <= dur < 28 or 52 < dur <= 60:
        pts += 1.5
    return max(0.0, min(10.0, pts)), flags


def score(ix: EpisodeIndex, cand: Candidate) -> Scored:
    info = _info(ix)
    lines = ix.lines_between(cand.start, cand.end)
    mean_int = sum(info[d.idx].intensity for d in lines) / len(lines) if lines else 0.0

    hook, hook_label, hook_line, f1 = _hook(ix, info, cand, lines)
    cliff, signals, cliff_line, withheld, f2 = _cliff(ix, info, cand, lines, mean_int)
    stand, f3, k = _standalone(ix, info, cand, lines)
    tension, changes = _tension(info, lines)
    pace, f4 = _pace(cand, lines)

    parts = {"hook": round(hook, 2), "cliffhanger": round(cliff, 2),
             "standalone": round(stand, 2), "tension": round(tension, 2), "pace": round(pace, 2)}
    total = round(sum(parts.values()), 2)
    flags = f1 + f2 + f3 + f4

    counts: dict[str, int] = {}
    for d in lines:
        if not d.voiceover:
            counts[_spk(d)] = counts.get(_spk(d), 0) + 1
    main = [n for n, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:2]]
    body = (f"{changes + 1} speaker turns, mainly {main[0]} vs {main[1]}" if len(main) >= 2
            else "a single-speaker scene")
    cliff_label = signals[0] if signals else "with no strong cliffhanger signal"
    if len(signals) > 1:
        cliff_label += f" (+ {signals[1]})"
    why = f"Opens on {hook_label}; {body}; {cliff_label}."

    return Scored(cand=cand, total=total, parts=parts, flags=flags, hook_label=hook_label,
                  cliff_label=cliff_label, hook_line=hook_line, cliff_line=cliff_line,
                  withheld=withheld, why=why, n_lines=len(lines), n_speakers=k)
