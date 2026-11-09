# What changed from v1, and why

Every change below was made because of something **verified** in an audit of the v1 submission.

## Audit findings (v1)

| # | Finding | How it was verified |
|---|---|---|
| 1 | Not re-runnable: following `EXECUTION_GUIDE.md` from a clean clone, **9 of 15 steps crashed** | Ran the documented steps in order on a fresh copy without `outputs/` |
| 2 | Pipeline silently depended on a hand-built, git-ignored `editorial_review_sheet.csv` | Same run: `FileNotFoundError` at `rank_final_shortlist.py` and everything after it |
| 3 | The ranked "shortlist" came from 4 hand-picked episodes (`selected_episodes = [1, 11, 28, 46]`), not all 50 | `create_editorial_shortlist.py`; the review sheet holds episodes 1, 11, 22, 28, 46 only |
| 4 | The scorer ranked the author's own human picks 395th-3,020th of 4,308 (EP001 at 1,515th) | `outputs/editorial_automated_comparison.csv` |
| 5 | Its #1 pick started mid-conversation (violates "makes sense on its own") | Read `EP032_0007500_50` |
| 6 | "NLP" = counting words like *but / what / who* over camera and action text too; the delivery tags in every dialogue line (`(Cold, Threatening)`) were parsed, then discarded | `extract_nlp_features.py` |
| 7 | Windows were a blind 5-second grid: cuts landed mid-sentence | `generate_candidates.py` |
| 8 | Required output (episode, every segment, hook, cliffhanger, why, ranked, all episodes) did not exist | Only 5 rows with hook/cliffhanger text, hand-written |
| 9 | Repo hygiene: 127 MB zip (contained `.venv`), ~50 scripts (many one-off `inspect_*`), two READMEs that disagreed (4 vs 5 reviewed) | Zip listing |

Things that were **fine** and kept: timestamp parsing (re-implemented independently, it reproduces v1's 3,727 blocks / 100 scenes
exactly and finds the same EP22 0.3 s anomaly), the pinned dependency versions (all exist), the honest limitation statements,
the EP46 failure-case idea.

## What replaced it, and why

| Change | Why |
|---|---|
| One package, one command (`python -m promo_finder run`) | #1, #2: must run on a new input in the interview |
| Tolerant parser; a bad file is reported, never fatal | A new show may have format quirks |
| Clean-cut candidates: shot-aligned cuts, never through a line or a continued sentence, hook inside 3 s by construction | #7 and the brief's hook rule |
| Dialogue-only, tag-aware scoring with explainable sub-scores and flags | #6; an editor must be able to argue with a rank |
| All 50 episodes ranked, with the brief's exact output fields, a "post first" list capped at 2 per episode | #3, #8 |
| Optional LLM judge on a shortlist only; never writes timestamps or quotes; provider/model are config; cached; budget-guarded; heuristic fallback | The brief rewards model-swappability; semantic judgement (loaded vs procedural question) is beyond keywords |
| Evaluation with baselines (random windows, "last window", v1) instead of Spearman on n=5 | A number without a baseline proves nothing |
| 42 tests, including a mock server for both LLM provider formats | Verify before trusting; the LLM path cannot be called live from the build environment |
| Streamlit app with upload + folder + inspector | A recruiter can try a new pack without a terminal |
| `sample_data/` (invented story) | Repo runs without confidential data |
| `.env` loader, `.gitignore` for data/outputs | Usability; confidentiality |
| v1 scripts removed from the tree (still in git history) | #9 |

## Bugs found in the new code *by testing or self-review* (and fixed)

1. A "zip-slip guard" I wrote did nothing (it only `continue`d before `extractall`). Removed; Python's `zipfile` already strips unsafe paths.
2. A candidate end could be snapped forward over another spoken line, mislabeling the closing line; and cuts could slice a slap or a door slam. Fixed with swallow/straddle checks.
3. My first quote-fidelity check glued hook and cliffhanger together and reported 20 false failures (0 real). Checker fixed.
4. The candidate generator could not reach the true episode end in 18 of 50 episodes (silent closing shot > 2.5 s). Fixed.
5. A stitched promo's id collided with a normal promo sharing its first start and last end (caught by a unit test). IDs now encode every segment.
6. The app kept showing heuristic results after switching to LLM mode (caught by a UI test). Results are now tied to the settings that produced them.

## Changes made *after* seeing evaluation results (disclosed because they make later numbers optimistic)

* The first evaluation showed the scorer ignored the writers' own cliffhanger placement (best episode-ending window ranked 165th for EP1).
  Evidence for the prior: 41 of 49 next-episode continuity notes open with a continuation phrase and 11 describe the cliffhanger outright.
  So the episode-end bonus was raised 7 -> 12 and a visual-reveal cue (+5) was added. Cliffhanger-note agreement (top-3) moved **3/10 -> 6/10**,
  which is in-sample for those 10 episodes. Top-1 stayed 1/10.
* By design (not tuned): every episode's list always includes its best episode-ending cut, labelled `episode-ending`.
  Consequence: top-3 agreement now equals the trivial "final window" baseline (6/10). The tool's added value is clean cut points,
  explanations and mid-episode alternatives, not a better episode-end detector.
* Weights were then **frozen**; no further tuning against the 10-episode or 5-pick checks.

## Not done / not verified

* The LLM judge has **not been run against a live model** (no API access from the build environment). Plumbing is tested against a mock server only.
* `--stitch` is implemented and unit-tested for validity but never beat a continuous cut in a check of the first 12 episodes (best stitched promo was 0.6-14 points lower, none found for 2 episodes),
  so it is off and no stitched promo is in the outputs.
* No video: nothing about acting, audio or framing can be judged.
