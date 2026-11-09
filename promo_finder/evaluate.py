"""Quality checks that mean something.

v1's "validation" was five human scores vs. the scorer (Spearman 0.447, n=5) plus
data-integrity checks. Here there are three layers, each honest about its limits:

1. HARD CHECKS - run on 100 % of promos, no judgement involved: length, cut points,
   hook timing, quote fidelity, distinctness, ordering.
2. AGREEMENT WITH YOUR HUMAN PICKS - eval/human_picks.csv (5 windows over 4 episodes).
3. AGREEMENT WITH THE SHOW'S OWN CLIFFHANGER NOTES - for 11 episodes the next
   episode's CONTINUITY NOTES literally describe how the previous one ended
   ("Episode 11's cliffhanger where the Constable pulls Gerald's planted pocket
   watch..."). That is a label that nobody on this project wrote for the tool.

Layers 2 and 3 are small. They are compared with baselines (v1, "last 45 s",
random clean-cut windows) because a number without a baseline proves nothing.
"""
from __future__ import annotations

import csv
import math
import random
import re
from collections import Counter
from pathlib import Path

from .candidates import EpisodeIndex, generate
from .models import ACTION, DIALOGUE, SOUND_FX, Episode

STOP = set("""
a an the and or but if then so of to in on at by for with from as is are was were be been being it its this that
these those he she they them his her their him you your yours i me my we our us who whom whose which what when
where why how not no nor into onto over under again further once here there all any both each few more most other
some such only own same than too very can will just don should now has have had having does did doing would could
about after before above below up down out off while until during through between against within without upon
""".split())
_SUFFIXES = ("ingly", "edly", "ing", "ers", "er", "ed", "es", "ly", "s")


def _stem(w: str) -> str:
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def _tokens(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in STOP]


def iou(a0, a1, b0, b1) -> float:
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = (a1 - a0) + (b1 - b0) - inter
    return inter / union if union > 0 else 0.0


# --------------------------------------------------------------------------- 1
def hard_checks(promos: list[dict], episodes: list[Episode], min_s=20.0, max_s=60.0,
                max_overlap=0.25) -> list[dict]:
    by_ep = {e.number: e for e in episodes}
    ix_cache: dict[int, EpisodeIndex] = {}

    def ix_of(n):
        if n not in ix_cache:
            ix_cache[n] = EpisodeIndex(by_ep[n])
        return ix_cache[n]

    fails: dict[str, list[str]] = {k: [] for k in (
        "length_20_60s", "segments_inside_episode", "segments_ordered_no_overlap",
        "no_cut_through_a_spoken_line", "hook_within_3s", "quotes_exist_in_source",
        "distinct_within_episode", "ranked_by_score", "unique_ids")}

    for p in promos:
        pid, ep = p["promo_id"], by_ep.get(p["episode"])
        segs = p["segments"]
        if ep is None:
            for k in fails:
                fails[k].append(f"{pid}: episode missing")
            continue
        if not (min_s - 1e-6 <= sum(g["end"] - g["start"] for g in segs) <= max_s + 1e-6):
            fails["length_20_60s"].append(pid)
        if any(g["start"] < -1e-6 or g["end"] > ep.duration + 0.5 or g["end"] <= g["start"] for g in segs):
            fails["segments_inside_episode"].append(pid)
        if any(b["start"] < a["end"] - 1e-6 for a, b in zip(segs, segs[1:])) and not p.get("stitched"):
            fails["segments_ordered_no_overlap"].append(pid)
        if p.get("stitched") and any(b["start"] < a["end"] + 0.0 for a, b in zip(segs, segs[1:])):
            fails["segments_ordered_no_overlap"].append(pid)
        ix = ix_of(ep.number)
        if any(ix.straddles(g["start"]) or ix.straddles(g["end"]) for g in segs):
            fails["no_cut_through_a_spoken_line"].append(pid)
        first = segs[0]
        opener_ok = any(e.kind in (DIALOGUE, ACTION) and first["start"] - 0.02 <= e.start <= first["start"] + 3.0 + 1e-6
                        for e in ep.events)
        if not opener_ok:
            fails["hook_within_3s"].append(pid)
        source = " ".join(e.text for e in ep.events)
        for field in ("hook", "cliffhanger"):  # checked one field at a time
            txt = p.get(field) or ""
            quotes = re.findall(r"\u201c(.+?)\u201d", txt)
            quotes += re.findall(r"\[(?:ACTION|SOUND_FX)\] (.+?)(?:  \u2192|$)", txt)
            if any(q not in source for q in quotes):
                fails["quotes_exist_in_source"].append(f"{pid}:{field}")
                break

    by_ep_promos: dict[int, list[dict]] = {}
    for p in promos:
        by_ep_promos.setdefault(p["episode"], []).append(p)
    for n, lst in by_ep_promos.items():
        for i, a in enumerate(lst):
            for b in lst[i + 1:]:
                s0, s1 = a["segments"][0], b["segments"][0]
                inter = min(s0["end"], s1["end"]) - max(s0["start"], s1["start"])
                shorter = min(s0["end"] - s0["start"], s1["end"] - s1["start"])
                if inter > 0 and inter / shorter > max_overlap + 1e-6 and not (a.get("stitched") or b.get("stitched")):
                    fails["distinct_within_episode"].append(f"{a['promo_id']}~{b['promo_id']}")
    scores = [p["score"] for p in sorted(promos, key=lambda p: p["rank"])]
    if any(x < y - 1e-9 for x, y in zip(scores, scores[1:])):
        fails["ranked_by_score"].append("rank order violates score order")
    dup = [k for k, v in Counter(p["promo_id"] for p in promos).items() if v > 1]
    fails["unique_ids"] += dup
    return [{"check": k, "passed": not v, "failures": len(v), "examples": v[:3], "n": len(promos)}
            for k, v in fails.items()]


# --------------------------------------------------------------------------- 2
def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _top_k_windows(promos, ep, k):
    lst = sorted((p for p in promos if p["episode"] == ep), key=lambda p: p["rank_in_episode"])[:k]
    return [(p["segments"][0]["start"], p["segments"][-1]["end"], p) for p in lst]


def human_agreement(promos: list[dict], human_csv: Path, reject_csv: Path | None = None,
                    v1_csv: Path | None = None, k: int = 3, thresh: float = 0.5,
                    episodes: list[Episode] | None = None, seed: int = 7, trials: int = 400) -> dict:
    human = _read_csv(human_csv)
    rng = random.Random(seed)
    by_ep = {e.number: e for e in (episodes or [])}
    v1 = _read_csv(v1_csv) if v1_csv and Path(v1_csv).exists() else []
    rows = []
    for h in human:
        ep, h0, h1 = int(h["episode"]), float(h["start_s"]), float(h["end_s"])
        mine = _top_k_windows(promos, ep, k)
        best = max((iou(h0, h1, a, b) for a, b, _ in mine), default=0.0)
        top1 = iou(h0, h1, mine[0][0], mine[0][1]) if mine else 0.0
        v1_eps = sorted((r for r in v1 if int(r["episode"]) == ep), key=lambda r: int(r["v1_global_rank"]))[:k]
        v1_best = max((iou(h0, h1, float(r["start_s"]), float(r["end_s"])) for r in v1_eps), default=0.0)
        rand_p = None
        if ep in by_ep:  # chance that k random clean-cut windows would "hit" by luck
            pool = generate(by_ep[ep])
            ok = sum(any(iou(h0, h1, c.start, c.end) >= thresh for c in rng.sample(pool, min(k, len(pool))))
                     for _ in range(trials))
            rand_p = ok / trials
        rows.append({"episode": ep, "human": f"{h0:g}-{h1:g}s", "random_hit_prob": None if rand_p is None else round(rand_p, 2),
                     "v2_top1_iou": round(top1, 2),
                     f"v2_best_of_top{k}_iou": round(best, 2), f"v1_best_of_top{k}_iou": round(v1_best, 2),
                     "v2_hit": best >= thresh, "v1_hit": v1_best >= thresh})
    rp = [r["random_hit_prob"] for r in rows if r["random_hit_prob"] is not None]
    out = {"rows": rows, "k": k, "iou_threshold": thresh,
           "random_expected_hits": round(sum(rp), 2) if rp else None,
           "v2_hits": sum(r["v2_hit"] for r in rows), "v1_hits": sum(r["v1_hit"] for r in rows), "n": len(rows),
           "random_expected_hits": round(sum(r["random_hit_prob"] or 0 for r in rows), 2)}
    if reject_csv and Path(reject_csv).exists():
        rej = []
        for r in _read_csv(reject_csv):
            ep, r0, r1 = int(r["episode"]), float(r["start_s"]), float(r["end_s"])
            mine = _top_k_windows(promos, ep, 1)
            if mine:
                a, b, p = mine[0]
                rej.append({"episode": ep, "rejected_window": f"{r0:g}-{r1:g}s",
                            "v2_top1_window": f"{a:g}-{b:g}s", "iou_with_rejected": round(iou(r0, r1, a, b), 2),
                            "v2_top1_flags": p["flags"], "v2_top1_cliffhanger": p["cliffhanger"][:90]})
        out["rejected_cases"] = rej
    return out


# --------------------------------------------------------------------------- 3
_NOTE = re.compile(r"Episode\s+(\d+)['\u2019]s\s+(?:[A-Za-z]+\s+)?cliffhanger(?P<rest>[^.;]*)", re.I)


def cliffhanger_notes(episodes: list[Episode]) -> dict[int, str]:
    """{episode N: description of how N ends} read from episode N+1's continuity notes."""
    found: dict[int, str] = {}
    for ep in episodes:
        m = _NOTE.search(ep.continuity or "")
        if not m:
            continue
        n, rest = int(m.group(1)), m.group("rest").strip(" ,:")
        if len(rest) < 12:  # "...cliffhanger. Gerald has turned away..." -> use the next sentence
            tail = ep.continuity[m.end():].lstrip(". ")
            rest = tail.split(".")[0]
        found.setdefault(n, rest)
    return found


def _tail_tokens(ep: Episode, w1: float, tail_s: float) -> set[str]:
    lo = w1 - tail_s
    return set(_tokens(" ".join(e.text for e in ep.events if e.end > lo and e.start < w1)))


def _generic_terms(episodes: list[Episode], df_cut: float = 0.30) -> set[str]:
    """Words (mostly character names) present in >30 % of episodes carry no signal.
    On tiny inputs (<10 episodes) document frequency means nothing, so nothing is filtered."""
    if len(episodes) < 10:
        return set()
    df: Counter = Counter()
    for ep in episodes:
        df.update(set(_tokens(" ".join(e.text for e in ep.events))))
    return {t for t, c in df.items() if c / len(episodes) > df_cut}


def note_hit(ep: Episode, window_end: float, keys: set[str], tail_s: float, thresh: float) -> tuple[bool, float]:
    recall = len(keys & _tail_tokens(ep, window_end, tail_s)) / len(keys) if keys else 0.0
    return recall >= thresh, recall


def cliffhanger_note_eval(promos: list[dict], episodes: list[Episode], v1_csv: Path | None = None,
                          k: int = 3, tail_s: float = 15.0, thresh: float = 0.4, seed: int = 7,
                          draws: int = 200) -> dict:
    by_ep = {e.number: e for e in episodes}
    generic = _generic_terms(episodes)
    notes = cliffhanger_notes(episodes)
    v1 = _read_csv(v1_csv) if v1_csv and Path(v1_csv).exists() else []
    rng = random.Random(seed)
    rows, tot = [], Counter()
    rand_hits = 0.0
    for n, desc in sorted(notes.items()):
        ep = by_ep.get(n)
        if ep is None:
            continue
        keys = {t for t in _tokens(desc) if t not in generic}
        if len(keys) < 3:
            continue
        mine = _top_k_windows(promos, n, k)
        if not mine:
            continue
        hits = [note_hit(ep, b, keys, tail_s, thresh) for _, b, _ in mine]
        v1w = sorted((r for r in v1 if int(r["episode"]) == n), key=lambda r: int(r["v1_global_rank"]))[:k]
        v1h = [note_hit(ep, float(r["end_s"]), keys, tail_s, thresh) for r in v1w]
        last = note_hit(ep, ep.duration, keys, tail_s, thresh)
        pool = generate(ep)
        pool_hit = sum(note_hit(ep, c.end, keys, tail_s, thresh)[0] for c in rng.sample(pool, min(draws, len(pool))))
        pool_rate = pool_hit / min(draws, len(pool))
        rand_hits += pool_rate
        rows.append({"episode": n, "keys": sorted(keys),
                     "v2_top1_recall": round(hits[0][1], 2), "v2_top1_hit": hits[0][0],
                     "v2_anyTopK_hit": any(h for h, _ in hits),
                     "v1_top1_hit": bool(v1h and v1h[0][0]), "v1_anyTopK_hit": any(h for h, _ in v1h),
                     "last_window_hit": last[0], "random_rate": round(pool_rate, 2),
                     "v2_top1_window": f"{mine[0][0]:g}-{mine[0][1]:g}s", "episode_len": round(ep.duration, 1),
                     "note": desc[:120]})
        tot["n"] += 1
        tot["v2_top1"] += hits[0][0]
        tot["v2_anyk"] += any(h for h, _ in hits)
        tot["v1_top1"] += bool(v1h and v1h[0][0])
        tot["v1_anyk"] += any(h for h, _ in v1h)
        tot["last"] += last[0]
    return {"rows": rows, "n": tot["n"], "k": k, "tail_s": tail_s, "recall_threshold": thresh,
            "v2_top1_hits": tot["v2_top1"], "v2_anyk_hits": tot["v2_anyk"],
            "v1_top1_hits": tot["v1_top1"], "v1_anyk_hits": tot["v1_anyk"],
            "last_window_hits": tot["last"], "random_expected_hits": round(rand_hits, 1)}


def evaluate_all(promos, episodes, eval_dir: Path, k: int = 3) -> dict:
    eval_dir = Path(eval_dir)
    return {
        "hard_checks": hard_checks(promos, episodes),
        "human_agreement": human_agreement(promos, eval_dir / "human_picks.csv",
                                           eval_dir / "human_rejects.csv", eval_dir / "v1_baseline.csv", k,
                                           episodes=episodes),
        "cliffhanger_notes": cliffhanger_note_eval(promos, episodes, eval_dir / "v1_baseline.csv", k),
    }
