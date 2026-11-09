"""Command line: ``python -m promo_finder run --input data/raw --out outputs``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .envfile import load_dotenv
from .parse import load_inputs
from .pipeline import RunConfig, run
from .report import write_outputs


def _default_input() -> str:
    for cand in ("data/raw", "sample_data"):
        p = Path(cand)
        if p.is_dir() and any(p.rglob("*.txt")):
            return cand
    return ""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="promo_finder", description="Find 20-60 s promo clips in microdrama screenplays.")
    ap.add_argument("--version", action="version", version=f"promo_finder {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="parse -> score -> rank -> write outputs")
    r.add_argument("--input", "-i", default=_default_input(), help="folder, .txt file or .zip of screenplays "
                   "(default: data/raw, else sample_data)")
    r.add_argument("--out", "-o", default="outputs", help="output folder (default: outputs)")
    r.add_argument("--per-episode", type=int, default=3, help="distinct promos kept per episode (default 3)")
    r.add_argument("--recommended", type=int, default=15, help="how many top promos are marked 'post first'")
    r.add_argument("--max-recommended-per-episode", type=int, default=2,
                   help="cap on 'post first' promos from one episode (default 2)")
    r.add_argument("--min-seconds", type=float, default=20.0)
    r.add_argument("--max-seconds", type=float, default=60.0)
    r.add_argument("--no-episode-end", action="store_true", help="do not force the episode-ending cut into each list")
    r.add_argument("--stitch", action="store_true", help="experimental two-segment promos")
    g = r.add_argument_group("LLM judge (optional; default is the free offline heuristic judge)")
    g.add_argument("--judge", choices=("heuristic", "llm"), default="heuristic")
    g.add_argument("--llm-provider", choices=("anthropic", "openai"), help="or env LLM_PROVIDER")
    g.add_argument("--llm-model", help="or env LLM_MODEL (check your provider's current model names)")
    g.add_argument("--llm-base-url", help="or env LLM_BASE_URL (OpenAI-compatible endpoints)")
    g.add_argument("--llm-topk", type=int, default=6, help="windows per episode sent to the LLM (default 6)")
    g.add_argument("--llm-weight", type=float, default=0.6, help="final = w*LLM + (1-w)*heuristic (default 0.6)")
    g.add_argument("--max-llm-calls", type=int, default=None, help="hard budget on paid calls")
    g.add_argument("--cache-dir", default=".llm_cache", help="LLM answer cache (default .llm_cache)")
    g.add_argument("--dry-run", action="store_true", help="LLM mode: print the call/token estimate and stop")
    r.add_argument("--eval-dir", help="folder with human_picks.csv / v1_baseline.csv for the extra agreement checks "
                   "(only meaningful for the original pack)")
    r.add_argument("--quiet", "-q", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv()  # optional .env with LLM_* keys
    say = (lambda *_a, **_k: None) if args.quiet else (lambda *a, **k: print(*a, **k, flush=True))

    if not args.input:
        print("error: no input found. Pass --input <folder|.txt|.zip> or put screenplays in data/raw", file=sys.stderr)
        return 2
    try:
        episodes, parse_report = load_inputs(args.input)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    bad = [r for r in parse_report if r["status"] in ("error", "skipped")]
    for r in bad:
        print(f"warning: {r['file']}: {r['warnings']}", file=sys.stderr)
    if not episodes:
        print("error: no screenplay could be parsed from the input (see warnings above)", file=sys.stderr)
        return 2
    say(f"Parsed {len(episodes)} episode(s) from {args.input}"
        + (f" ({len(bad)} file(s) skipped)" if bad else ""))

    cfg = RunConfig(per_episode=args.per_episode, min_s=args.min_seconds, max_s=args.max_seconds,
                    judge=args.judge, llm_topk=args.llm_topk, llm_weight=args.llm_weight,
                    max_llm_calls=args.max_llm_calls, include_episode_end=not args.no_episode_end,
                    stitch=args.stitch, recommended_top=args.recommended,
                    max_recommended_per_episode=args.max_recommended_per_episode)
    client = None
    if args.judge == "llm":
        from .llm import LLMError, make_client
        try:
            client = make_client(args.llm_provider, args.llm_model, base_url=args.llm_base_url,
                                 cache_dir=args.cache_dir, max_calls=args.max_llm_calls)
        except LLMError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.dry_run:
            from .candidates import EpisodeIndex, generate
            from .llm import estimate
            from .scoring import score
            from .select import pick_distinct
            idx, picks = {}, {}
            for ep in episodes:
                idx[ep.number] = EpisodeIndex(ep)
                sc = [score(idx[ep.number], c) for c in generate(ep, cfg.min_s, cfg.max_s, ix=idx[ep.number])]
                picks[ep.number] = pick_distinct(sc, cfg.llm_topk, cfg.max_overlap)
            est = estimate(picks, episodes, idx)
            est["episodes"] = len(episodes)
            est["note"] = "approximate: characters/4; multiply by your provider's per-token prices"
            Path(args.out).mkdir(parents=True, exist_ok=True)
            (Path(args.out) / "llm_estimate.json").write_text(json.dumps(est, indent=2), encoding="utf-8")
            print(json.dumps(est, indent=2))
            return 0

    def progress(i, n, msg):
        if not args.quiet and (i == n or i % 10 == 0):
            print(f"  [{i}/{n}] {msg}", flush=True)

    result = run(episodes, cfg, llm_client=client, progress=progress)
    extra = None
    if args.eval_dir:
        from .evaluate import evaluate_all
        extra = {k: v for k, v in evaluate_all(result.promos, episodes, args.eval_dir).items() if k != "hard_checks"}
    summary = write_outputs(result, episodes, parse_report, args.out, args.input, extra_eval=extra)
    say(f"\n{summary['promos']} promos ranked ({summary['recommended']} marked 'post first') "
        f"from {summary['candidate_windows']:,} windows in {summary['seconds']}s")
    say("Hard checks: " + ("all passed" if summary["hard_checks_passed"] else "SOME FAILED - see quality_report.md"))
    for n in result.notes:
        say("note:", n)
    say(f"Outputs written to {args.out}/  (start with promos_ranked.md)")
    return 0 if summary["hard_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
