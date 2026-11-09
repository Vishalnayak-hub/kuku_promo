# Kuku Promo Finder

Reads microdrama screenplays and finds the best **20–60 second promo clips**: a hook in the first
3 seconds, a cliffhanger ending, and a scene that makes sense to someone who has never seen the show.
For every promo it gives the **episode, the start/end of every segment, the hook, the cliffhanger,
the line that is withheld after the cut, and a one-line "why it works"** — ranked across all episodes.

```
screenplays ─► parse ─► 34k clean-cut windows ─► heuristic judge ─► (optional LLM judge, shortlist only)
            ─► distinct picks per episode ─► global ranking ─► CSV / JSON / Markdown + quality report
```

## Quick start (2 minutes)

```bash
python -m venv .venv
# Windows PowerShell:  .\.venv\Scripts\Activate.ps1        macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

python -m promo_finder run                  # uses data/raw if present, otherwise the bundled sample_data
streamlit run app.py                        # the web app (opens http://localhost:8501)
```

* The **engine needs no packages at all** (standard library only). `requirements.txt` is for the web app.
* Written for Python 3.10+, tested on 3.12.
* `python -m promo_finder run` prints where it wrote everything; start with `outputs/promos_ranked.md`.

### Run it on a new input (what you do in the interview)

```bash
python -m promo_finder run --input path/to/new_show_folder --out outputs_new
python -m promo_finder run --input pack.zip --out outputs_new          # a .zip works too
```
or open the app → *Input → Upload files* → drop the `.txt` screenplays (or one `.zip`) → results appear.
One unreadable file never stops a run: it is skipped and listed in `parse_report.csv`.

## What you get (`outputs/`)

| File | What it is |
|---|---|
| `promos_ranked.md` | Human-readable: the "post first" promos with hook, cliffhanger, transcript |
| `promos_ranked.csv` | One row per promo (open in Excel): episode, segments, hook, cliffhanger, cut_before, why, scores, flags |
| `promos_ranked.json` | Same plus the full transcript of every promo and the LLM verdicts |
| `quality_report.md/.json` | 9 hard checks on every promo + agreement with the show's own cliffhanger notes |
| `parse_report.csv` | Per-file parse status and warnings |
| `run_summary.json` | Settings, counts, timing, LLM token usage |

`segments` lists every stretch **in play order** (`00:00.00-00:48.00`). Single-segment promos are the norm;
`--stitch` (experimental, off) can add two-segment "cold open + ending" promos.

## How it decides

1. **Parse** each file (CAMERA / ACTION / SOUND FX / dialogue blocks, with the screenwriter's delivery tags such as `(Cold, Threatening)`).
2. **Clean-cut windows.** Every 20–60 s window that opens on the first frame of a shot whose dialogue/action starts within 3 s,
   closes on the last frame of a shot, never cuts through a spoken line or splits a sentence the script continues.
3. **Heuristic judge (free, offline, deterministic)** — 100 points: hook 25, cliffhanger 30, standalone 15, tension 20, pace 10.
   Every sub-score and penalty is returned, so any rank can be explained. Delivery tags drive emotion; it reads the line
   *after* the cut to see what is withheld.
4. **LLM judge (optional)** re-scores only a shortlist (~170 calls for 50 episodes). It returns scores and a one-line why;
   it **never writes timestamps or quotes** — cuts and quoted lines always come from the script. Provider and model are config.
5. **Pick and rank.** Distinct promos per episode (≤25 % overlap), the episode's own cliffhanger cut is always offered,
   global ranking by score, and a "post first" list capped at 2 per episode.

### LLM mode

```bash
cp .env.example .env            # then fill LLM_MODEL and LLM_API_KEY  (Windows: copy .env.example .env)
python -m promo_finder run --judge llm --dry-run     # prints calls/tokens estimate, sends nothing
python -m promo_finder run --judge llm --max-llm-calls 200
```
Swap provider or model with `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` (or `--llm-*` flags); no code change.
Answers are cached in `.llm_cache/`, so re-runs and interrupted runs are free. Bad/malformed answers fall back to the
heuristic score for that window and are flagged. **This path is tested against a mock server, not yet against a live model** — see
`docs/CHANGES_FROM_V1.md` and run it once with your key before relying on it.

## Tests and quality checks

```bash
pip install -r requirements-dev.txt
pytest -q                                     # 42 tests: parser, cuts, scoring, selection, CLI, LLM (mock server), web app
python -m promo_finder run --eval-dir eval    # adds agreement with the earlier human picks (original pack only)
```
Results on the 50-episode pack, honest numbers, failures and the baselines they are compared with are in
`docs/Kuku_Promo_Finder_Solution.pdf` and `docs/REVIEW_NOTES.md`.

## Folder layout

```
promo_finder/   the engine (parse, candidates, scoring, select, llm, stitch, evaluate, report, cli)
app.py          Streamlit web app
sample_data/    3 invented episodes (not Kuku content) so everything runs without the confidential pack
eval/           small label files for the quality checks (timestamps only, no screenplay text)
tests/          pytest suite
docs/           solution PDF, review notes, change log, walkthrough script
data/raw/       the input pack goes here (git-ignored)
```

## Confidentiality

The input pack is Kuku's content. `data/`, `outputs/` and `submission/raw_outputs/` are git-ignored: outputs quote
screenplay lines, so share them only through the Drive link the assignment asks for, not a public repository.

## Known limits (details in the solution doc)

* Input is **text, not video**: acting, audio, framing and edit quality are invisible. An editor must watch every cut.
* The heuristic cannot tell a loaded question from a procedural one ("What wedding?" vs "You served beside the accused?").
  That is the job of the LLM judge, which has not yet been run live.
* Top picks lean on mid/late episodes that need backstory; no early-episode bias is applied.
* Cliffhanger agreement with the show's notes is measured on only 10 episodes and, after one documented change, is in-sample.
