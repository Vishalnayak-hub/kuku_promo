"""Selection: from thousands of scored windows to a short, distinct, ranked list.

v1 de-duplicated at >=70 % overlap and still left 268 near-identical windows.
A promo list is only useful if each entry is a *different moment*, so here two
promos in the same episode may share at most ``max_overlap`` of the shorter one.
"""
from __future__ import annotations

from .scoring import Scored


def overlap_ratio(a: Scored, b: Scored) -> float:
    inter = min(a.cand.end, b.cand.end) - max(a.cand.start, b.cand.start)
    if inter <= 0:
        return 0.0
    return inter / min(a.cand.duration, b.cand.duration)


def sort_key(s: Scored):
    return (-s.total, s.cand.episode, s.cand.start, s.cand.end)


def pick_distinct(scored: list[Scored], n: int, max_overlap: float = 0.25) -> list[Scored]:
    """Top-``n`` windows of ONE episode that overlap each other by <= max_overlap."""
    picks: list[Scored] = []
    for s in sorted(scored, key=sort_key):
        if all(overlap_ratio(s, p) <= max_overlap for p in picks):
            picks.append(s)
            if len(picks) == n:
                break
    return picks


def rank_global(picks: list[Scored]) -> list[Scored]:
    return sorted(picks, key=sort_key)


def best_episode_ending(scored: list[Scored], duration: float) -> Scored | None:
    """Highest-scoring window that closes on the episode's own last frame."""
    ends = [s for s in scored if s.cand.end >= duration - 1.0]
    return min(ends, key=sort_key) if ends else None


def choose_picks(shortlist: list[Scored], ep_end: Scored | None, n: int,
                 max_overlap: float = 0.25) -> list[Scored]:
    """``n`` distinct promos for one episode.

    The writers end every episode on a cliffhanger, so when n >= 2 the best
    episode-ending cut is always offered next to the best peak moments (the
    ranking still goes by score - a weak ending simply sinks in the list).
    """
    if ep_end is None or n < 2:
        return pick_distinct(shortlist, n, max_overlap)
    rest = [s for s in shortlist if s is not ep_end and overlap_ratio(s, ep_end) <= max_overlap]
    return [ep_end] + pick_distinct(rest, n - 1, max_overlap)


def ends_at_episode_end(s: Scored, duration: float) -> bool:
    return s.cand.end >= duration - 1.0
