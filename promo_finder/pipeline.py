"""End-to-end pipeline: screenplays in, ranked promos out.

    parse -> clean-cut candidates -> heuristic judge -> (optional LLM judge on the
    shortlist only) -> distinct picks per episode -> global ranking
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .candidates import EpisodeIndex, generate
from .models import Episode, fmt_ts
from .scoring import Scored, score
from .select import (best_episode_ending, choose_picks, ends_at_episode_end, pick_distinct,
                     rank_global)


@dataclass
class RunConfig:
    per_episode: int = 3  # distinct promos kept per episode
    min_s: float = 20.0  # brief: 20-60 s
    max_s: float = 60.0
    max_overlap: float = 0.25  # two promos of one episode may share <=25 %
    judge: str = "heuristic"  # "heuristic" | "llm"
    llm_topk: int = 6  # windows per episode sent to the LLM
    llm_weight: float = 0.6  # final = w*llm + (1-w)*heuristic
    max_llm_calls: int | None = None  # hard budget guard
    include_episode_end: bool = True  # always offer the best episode-ending cut
    stitch: bool = False  # experimental multi-segment promos
    recommended_top: int = 15  # how many to flag "post first"
    max_recommended_per_episode: int = 2  # ...but never more than this many from one episode


@dataclass
class RunResult:
    config: RunConfig
    promos: list[dict]  # ranked rows, ready to write
    n_episodes: int = 0
    n_candidates: int = 0
    seconds: float = 0.0
    llm_usage: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _transcript(ix: EpisodeIndex, start: float, end: float, offset: float = 0.0) -> list[dict]:
    rows = []
    for d in ix.lines_between(start, end):
        rows.append({"t": round(offset + d.start - start, 2), "speaker": d.who or d.speaker,
                     "tags": list(d.tags), "text": d.text, "voiceover": d.voiceover})
    return rows


def to_row(s: Scored, ix: EpisodeIndex) -> dict:
    """One promo -> one output row. ``segments`` lists every stretch in play order."""
    segs = [s.cand] + list(s.extra)
    transcript, offset = [], 0.0
    for seg in segs:
        transcript += _transcript(ix, seg.start, seg.end, offset)
        offset += seg.duration
    first = segs[0]
    return {
        "promo_id": f"EP{first.episode:03d}_" + "+".join(
            f"{int(round(g.start * 100)):05d}_{int(round(g.end * 100)):05d}" for g in segs),
        "episode": first.episode,
        "segments": [{"episode": g.episode, "start": g.start, "end": g.end,
                      "start_ts": fmt_ts(g.start), "end_ts": fmt_ts(g.end)} for g in segs],
        "start_ts": fmt_ts(first.start), "end_ts": fmt_ts(segs[-1].end),
        "duration": round(sum(g.duration for g in segs), 2),
        "hook_at_s": round(first.opener.start - first.start, 2),
        "hook": s.hook_line,
        "cliffhanger": s.cliff_line,
        "cut_before": s.withheld,
        "why": s.why,
        "score": s.total,
        "parts": s.parts,
        "flags": list(s.flags),
        "judge": s.judge,
        "llm": s.llm,
        "kind": "episode-ending" if s.cand.end >= ix.duration - 1.0 else "peak",
        "stitched": s.stitched,
        "ends_at_episode_end": ends_at_episode_end(s, ix.duration),
        "needs_editor_check": bool(s.flags) or s.stitched,
        "transcript": transcript,
    }


def run(episodes: list[Episode], cfg: RunConfig | None = None, llm_client=None,
        progress=None) -> RunResult:
    cfg = cfg or RunConfig()
    t0 = time.time()
    keep = cfg.llm_topk if cfg.judge == "llm" else cfg.per_episode
    picks_by_ep: dict[int, list[Scored]] = {}
    ep_ends: dict[int, Scored | None] = {}
    indexes: dict[int, EpisodeIndex] = {}
    n_cand = 0
    notes: list[str] = []

    for i, ep in enumerate(episodes):
        ix = EpisodeIndex(ep)
        indexes[ep.number] = ix
        cands = generate(ep, cfg.min_s, cfg.max_s, ix=ix)
        n_cand += len(cands)
        if not cands:
            notes.append(f"EP{ep.number}: no valid {cfg.min_s:.0f}-{cfg.max_s:.0f}s window "
                         f"(episode too short or too little dialogue)")
            continue
        scored = [score(ix, c) for c in cands]
        ep_end = best_episode_ending(scored, ix.duration) if cfg.include_episode_end else None
        ep_ends[ep.number] = ep_end
        shortlist = pick_distinct(scored, keep, cfg.max_overlap)
        if ep_end is not None and ep_end not in shortlist:
            shortlist.append(ep_end)  # judged too, so an LLM can weigh it fairly
        picks_by_ep[ep.number] = shortlist
        if progress:
            progress(i + 1, len(episodes), f"scored EP{ep.number}")

    usage: dict = {}
    if cfg.judge == "llm":
        if llm_client is None:
            raise ValueError("judge='llm' needs an llm_client (see promo_finder.llm.make_client)")
        from .llm import judge_shortlist
        usage = judge_shortlist(episodes, indexes, picks_by_ep, llm_client, cfg, progress, notes)
    for ep_no, lst in picks_by_ep.items():
        picks_by_ep[ep_no] = choose_picks(lst, ep_ends.get(ep_no), cfg.per_episode, cfg.max_overlap)

    if cfg.stitch:
        from .stitch import add_stitched
        add_stitched(episodes, indexes, picks_by_ep, cfg, notes)

    final = rank_global([s for lst in picks_by_ep.values() for s in lst])
    rows = []
    in_ep: dict[int, int] = {}
    rec_per_ep: dict[int, int] = {}
    n_rec = 0
    for rank, s in enumerate(final, 1):
        ix = indexes[s.cand.episode]
        row = to_row(s, ix)
        ep_no = row["episode"]
        in_ep[ep_no] = in_ep.get(ep_no, 0) + 1
        recommended = (n_rec < cfg.recommended_top
                       and rec_per_ep.get(ep_no, 0) < cfg.max_recommended_per_episode)
        if recommended:
            n_rec += 1
            rec_per_ep[ep_no] = rec_per_ep.get(ep_no, 0) + 1
        row.update(rank=rank, rank_in_episode=in_ep[ep_no], recommended=recommended)
        rows.append(row)
    return RunResult(config=cfg, promos=rows, n_episodes=len(episodes), n_candidates=n_cand,
                     seconds=round(time.time() - t0, 2), llm_usage=usage, notes=notes)
