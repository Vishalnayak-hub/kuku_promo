# 3-minute walkthrough script (screen recording, your own voice)

**0:00-0:25 - the problem.** "Editors watch every episode to pick promos. This tool reads the screenplays and ranks promo clips: a hook in
the first 3 seconds, a cliffhanger ending, and a scene that works on its own."

**0:25-1:10 - run it.** Terminal: `python -m promo_finder run` on `data/raw`. Show: 50 episodes, ~34k windows, ~4 s, "Hard checks: all passed".
Open `outputs/promos_ranked.md`: read promo #4 (EP36): hook, cliffhanger, **cut before** ("What wedding?" -> the answer is withheld), why.

**1:10-1:55 - the app.** `streamlit run app.py` -> *Upload files* -> drop a *different* set of screenplays (or `sample_data`) -> results appear.
Open *Inspect a promo*: hook line, cliffhanger, withheld line, score breakdown, transcript. Mention the flags ("check before posting").

**1:55-2:30 - what is AI and what is code.** Code: parsing, cut points, validation (an LLM never writes a timestamp or a quote).
Free heuristics score every window and pick a shortlist; an optional LLM re-scores only the shortlist (~170 calls for 50 episodes);
provider/model are config values. Show `.env.example`.

**2:30-3:00 - honesty.** Show `quality_report.md`: 9/9 hard checks; agreement with the show's own cliffhanger notes is only 1/10 top-1,
6/10 top-3, no better than "take the last window"; it cannot tell a loaded question from a procedural one; no video was seen.
Say what you would do next: run the LLM judge live and label 20+ promos with an editor.
