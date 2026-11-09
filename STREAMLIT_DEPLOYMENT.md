# Kuku Promo Finder — Streamlit deployment

This repository is configured to run directly with Streamlit.

## Files

- `app.py` — self-contained Streamlit application
- `requirements.txt` — Streamlit + pandas
- `data/raw/` — screenplay text files

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud

Set the main file to:

```text
app.py
```

The app accepts `.txt` screenplay files or a `.zip` containing screenplay `.txt` files.

## Important

The uploaded source archive did not contain the original `promo_finder/` Python package even though `app.py` imported it. Therefore this deployment version uses a self-contained implementation of the documented workflow instead of importing the missing package.

The app analyzes screenplay text, generates 20–60 second candidate windows, scores them on hook/cliffhanger/standalone/tension/pacing, ranks them, and exports CSV/JSON/Markdown results.

It does not analyze actual video footage.
