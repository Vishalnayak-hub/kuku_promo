# Execution guide

All commands run from the project root. Works on Windows, macOS, Linux (Python 3.10+).

## 1. One-time setup
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows PowerShell   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt       # only needed for the web app; the engine has no dependencies
```
PowerShell may block activation; if so run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first.

## 2. Run the finder
| Goal | Command |
|---|---|
| The assignment pack (put the 50 `.txt` files in `data/raw/`) | `python -m promo_finder run --out outputs` |
| The bundled sample show | `python -m promo_finder run --input sample_data --out outputs_sample` |
| A new folder / a zip | `python -m promo_finder run --input <folder or .zip> --out outputs_new` |
| More/fewer promos per episode | `--per-episode 5` |
| Experimental two-segment promos | `--stitch` |
| Everything quiet | `-q` |

Exit codes: `0` ok, `1` a hard quality check failed (see `quality_report.md`), `2` bad input (message explains why).

## 3. Web app
```bash
streamlit run app.py
```
Sidebar: pick a folder or upload files → promos appear. *Inspect a promo* shows hook, cliffhanger, the withheld line, score
breakdown and the transcript. Download CSV/JSON/Markdown from *Ranked promos*.

## 4. LLM judge (optional)
```bash
copy .env.example .env      # macOS/Linux: cp .env.example .env   - then fill LLM_MODEL and LLM_API_KEY
python -m promo_finder run --judge llm --dry-run          # estimate only, nothing is sent
python -m promo_finder run --judge llm --max-llm-calls 200 --out outputs_llm
```
Free tiers are enough (≈170 calls for the whole pack). Use another provider by changing `LLM_PROVIDER`
(`anthropic` or `openai`-compatible) and `LLM_BASE_URL`; see `.env.example`.

## 5. Tests
```bash
pip install -r requirements-dev.txt
pytest -q
```

## 6. Rebuild the solution PDF
```bash
python docs/build_solution_pdf.py
```

## Troubleshooting
| Symptom | Fix |
|---|---|
| `error: no input found` | put screenplays in `data/raw/` or pass `--input` |
| `warning: x.txt: ValueError: no timed blocks found` | that file is not in the screenplay format; it is skipped, the run continues |
| `no model set` / `no API key` | fill `LLM_MODEL` / `LLM_API_KEY` in `.env` (LLM mode only) |
| `HTTP 401/404 from anthropic` | wrong key or model name; check the provider's current model list |
| App shows "Input not found" | the folder path in the sidebar is wrong |
| Streamlit Cloud build fails | in *Advanced settings* choose Python 3.12 |
