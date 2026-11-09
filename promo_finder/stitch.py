"""Experimental: multi-segment promos ("cold open" + cliffhanger ending).

The brief allows a promo to join a few moments. The one pattern implemented here is the
classic trailer shape: a short, hard-hitting HOOK moment from early in an episode, then
a CLIFFHANGER ending from later in the *same* episode. It only fires when it beats the
episode's best single-segment promo AND the opening hook is clearly stronger than the
ending window's own opening - i.e. when stitching actually buys something.

Off by default (``--stitch``). Not validated: a join can break continuity in ways a
screenplay cannot show, so every stitched promo is flagged for an editor check.
"""
from __future__ import annotations

from .candidates import generate
from .scoring import Scored, score

GAP = 2.0  # seconds of untouched story required between the two segments
HOOK_RANGE = (8.0, 15.0)
END_RANGE = (12.0, 45.0)
PENALTY = 5.0  # a join always carries continuity risk
MIN_HOOK_ADVANTAGE = 5.0


def add_stitched(episodes, indexes, picks_by_ep, cfg, notes) -> int:
    added = 0
    for ep in episodes:
        ix = indexes[ep.number]
        singles = picks_by_ep.get(ep.number, [])
        best_single = max((s.total for s in singles), default=0.0)
        hooks = sorted((score(ix, c) for c in generate(ep, *HOOK_RANGE, ix=ix, min_lines=2)),
                       key=lambda s: -s.parts["hook"])[:15]
        ends = sorted((score(ix, c) for c in generate(ep, *END_RANGE, ix=ix)),
                      key=lambda s: -s.parts["cliffhanger"])[:15]
        best: Scored | None = None
        for a in hooks:
            for b in ends:
                total_len = a.cand.duration + b.cand.duration
                if b.cand.start < a.cand.end + GAP or not (cfg.min_s <= total_len <= cfg.max_s):
                    continue
                if a.parts["hook"] - b.parts["hook"] < MIN_HOOK_ADVANTAGE:
                    continue
                parts = {
                    "hook": a.parts["hook"], "cliffhanger": b.parts["cliffhanger"],
                    "standalone": round(0.8 * a.parts["standalone"], 2),
                    "tension": round(0.5 * (a.parts["tension"] + b.parts["tension"]), 2),
                    "pace": round(0.5 * (a.parts["pace"] + b.parts["pace"]), 2),
                }
                total = round(sum(parts.values()) - PENALTY, 2)
                if total <= best_single or (best and total <= best.total):
                    continue
                best = Scored(cand=a.cand, extra=[b.cand], stitched=True, total=total, parts=parts,
                              flags=["stitched: the join may break continuity - editor must check"],
                              hook_label=a.hook_label, cliff_label=b.cliff_label,
                              hook_line=a.hook_line, cliff_line=b.cliff_line, withheld=b.withheld,
                              n_lines=a.n_lines + b.n_lines, n_speakers=max(a.n_speakers, b.n_speakers),
                              why=(f"Cold open on {a.hook_label}, then jump to the episode's strongest ending: "
                                   f"{b.cliff_label}."))
        if best is not None:
            picks_by_ep.setdefault(ep.number, []).append(best)
            added += 1
    if added:
        notes.append(f"stitch: added {added} experimental two-segment promos (flagged for editor check)")
    return added
