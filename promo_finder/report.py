"""Write every output of a run: CSV, JSON, Markdown, parse report, quality report, summary.

Files are written exactly as the pipeline produced them (nothing is edited by hand), which is
what the assignment's "unedited outputs" folder needs.
"""
from __future__ import annotations

import csv
import json
import platform
from pathlib import Path

from . import __version__
from .evaluate import cliffhanger_note_eval, hard_checks
from .models import Episode
from .pipeline import RunResult

CSV_COLUMNS = [
    "rank", "recommended", "promo_id", "episode", "rank_in_episode", "kind", "segments", "start_ts",
    "end_ts", "duration", "hook_at_s", "hook", "cliffhanger", "cut_before", "why", "score",
    "hook_score", "cliffhanger_score", "standalone_score", "tension_score", "pace_score", "flags",
    "judge", "llm_verdict", "stitched", "needs_editor_check",
]


def _csv_row(p: dict) -> dict:
    return {
        "rank": p["rank"], "recommended": "yes" if p["recommended"] else "", "promo_id": p["promo_id"],
        "episode": p["episode"], "rank_in_episode": p["rank_in_episode"], "kind": p["kind"],
        "segments": " + ".join(f"{g['start_ts']}-{g['end_ts']}" for g in p["segments"]),
        "start_ts": p["start_ts"], "end_ts": p["end_ts"], "duration": p["duration"],
        "hook_at_s": p["hook_at_s"], "hook": p["hook"], "cliffhanger": p["cliffhanger"],
        "cut_before": p["cut_before"], "why": p["why"], "score": p["score"],
        "hook_score": p["parts"]["hook"], "cliffhanger_score": p["parts"]["cliffhanger"],
        "standalone_score": p["parts"]["standalone"], "tension_score": p["parts"]["tension"],
        "pace_score": p["parts"]["pace"], "flags": "; ".join(p["flags"]), "judge": p["judge"],
        "llm_verdict": (p.get("llm") or {}).get("verdict", ""), "stitched": "yes" if p["stitched"] else "",
        "needs_editor_check": "yes" if p["needs_editor_check"] else "",
    }


def markdown(result: RunResult, top: int = 15) -> str:
    """Table + transcripts for the 'post first' promos (``top`` kept for API compatibility)."""
    rows = [p for p in result.promos if p["recommended"]] or result.promos[:top]
    out = ["# Ranked promo clips", "",
           f"{len(rows)} promos from {result.n_episodes} episodes "
           f"({result.n_candidates:,} clean-cut windows scored, judge: {result.config.judge}). "
           f"The {len(rows)} below are marked **post first** (best score, at most "
           f"{result.config.max_recommended_per_episode} per episode); the full list is in promos_ranked.csv.", "",
           "Every start/end is a screenplay timestamp (mm:ss.xx from the start of the episode). "
           "The screenplay has no video: an editor must still watch each cut.", "",
           "| # | Episode | Segments | Len | Score | Why it works |", "|---|---|---|---|---|---|"]
    for p in rows:
        segs = " + ".join(f"{g['start_ts']}-{g['end_ts']}" for g in p["segments"])
        out.append(f"| {p['rank']} | EP{p['episode']:02d} | {segs} | {p['duration']:.0f}s | "
                   f"{p['score']:.1f} | {p['why'].replace('|', '/')} |")
    out += ["", "## Details of the 'post first' promos", ""]
    for p in rows:
        segs = " + ".join(f"{g['start_ts']}-{g['end_ts']}" for g in p["segments"])
        out += [f"### #{p['rank']} - EP{p['episode']:02d}  {segs}  ({p['duration']:.0f}s, score {p['score']:.1f})", "",
                f"- **Hook (first {p['hook_at_s']:.1f}s):** {p['hook']}",
                f"- **Cliffhanger:** {p['cliffhanger']}",
                f"- **Cut before:** {p['cut_before'] or '(episode ends)'}",
                f"- **Why:** {p['why']}",
                "- **Scores:** " + ", ".join(f"{k} {v:g}" for k, v in p["parts"].items()),
                ]
        if p["flags"]:
            out.append("- **Check before posting:** " + "; ".join(p["flags"]))
        llm = p.get("llm")
        if llm:
            out.append(f"- **LLM verdict:** {llm['verdict']} (overall {llm['overall']:g}); risk: {llm['risk']}")
        out += ["", "```"]
        out += [f"{t['t']:5.1f}s  {t['speaker']} ({', '.join(t['tags'][:2])}): {t['text']}" for t in p["transcript"]]
        out += ["```", ""]
    return "\n".join(out)


def quality_markdown(checks: list[dict], notes_eval: dict | None) -> str:
    out = ["# Quality report", "", "## Hard checks (every promo, no judgement involved)", "",
           "| Check | Result | Failures |", "|---|---|---|"]
    for c in checks:
        out.append(f"| {c['check']} | {'PASS' if c['passed'] else 'FAIL'} | {c['failures']} |")
    if notes_eval and notes_eval.get("n"):
        n = notes_eval
        out += ["", "## Agreement with the show's own cliffhanger notes", "",
                f"Read from the next episode's CONTINUITY NOTES; n = {n['n']} episodes; hit = the last "
                f"{n['tail_s']:g}s of the promo contain >= {n['recall_threshold']:.0%} of the note's rare key words.", "",
                "| Method | Top-1 | Any of top-3 |", "|---|---|---|",
                f"| this tool | {n['v2_top1_hits']}/{n['n']} | {n['v2_anyk_hits']}/{n['n']} |",
                f"| baseline: the episode's final window | {n['last_window_hits']}/{n['n']} | - |",
                f"| baseline: random clean-cut windows (expected) | {n['random_expected_hits']}/{n['n']} | - |"]
    else:
        out += ["", "_No cliffhanger notes found in this input, so that check was skipped._"]
    return "\n".join(out)


def write_outputs(result: RunResult, episodes: list[Episode], parse_report: list[dict], out_dir,
                  input_path: str = "", extra_eval: dict | None = None, top: int | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    top = top or result.config.recommended_top

    with open(out / "promos_ranked.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for p in result.promos:
            w.writerow(_csv_row(p))
    (out / "promos_ranked.json").write_text(json.dumps(result.promos, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "promos_ranked.md").write_text(markdown(result, top), encoding="utf-8")

    with open(out / "parse_report.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "status", "episode", "events", "warnings"])
        w.writeheader()
        w.writerows(parse_report)

    checks = hard_checks(result.promos, episodes, result.config.min_s, result.config.max_s,
                         result.config.max_overlap)
    notes_eval = cliffhanger_note_eval(result.promos, episodes)
    (out / "quality_report.md").write_text(quality_markdown(checks, notes_eval), encoding="utf-8")
    quality = {"hard_checks": checks, "cliffhanger_notes": notes_eval}
    if extra_eval:
        quality.update(extra_eval)
    (out / "quality_report.json").write_text(json.dumps(quality, indent=2, default=str), encoding="utf-8")

    summary = {
        "tool_version": __version__, "python": platform.python_version(), "input": str(input_path),
        "episodes": result.n_episodes, "candidate_windows": result.n_candidates,
        "promos": len(result.promos), "recommended": sum(1 for p in result.promos if p["recommended"]),
        "judge": result.config.judge, "config": result.config.__dict__,
        "seconds": result.seconds, "llm_usage": result.llm_usage, "notes": result.notes,
        "parse_errors": [r for r in parse_report if r["status"] in ("error", "skipped")],
        "hard_checks_passed": all(c["passed"] for c in checks),
    }
    (out / "run_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary
