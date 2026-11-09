"""
Kuku Promo Finder - standalone Streamlit web app.

Run:
    streamlit run app.py

This version is self-contained and does NOT import the missing
`promo_finder` package that caused ModuleNotFoundError on Streamlit Cloud.
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------

st.set_page_config(
    page_title="Kuku Promo Finder",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 Kuku Promo Finder")
st.caption(
    "Finds 20–60 second promo clips in microdrama screenplays using "
    "hook, cliffhanger, standalone quality, tension and pacing."
)


# ---------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------

@dataclass
class Event:
    kind: str
    start: float
    end: float
    speaker: str = ""
    delivery: str = ""
    text: str = ""


@dataclass
class Episode:
    number: int
    name: str
    text: str
    events: list[Event]


# ---------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------

TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\.(\d{2})")


def time_to_seconds(value: str) -> float:
    m = TIME_RE.search(value or "")
    if not m:
        return 0.0
    return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 100.0


def seconds_to_ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes:02d}:{remainder:05.2f}"


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def extract_episode_number(text: str, filename: str) -> int:
    m = re.search(r"EPISODE NUMBER:\s*Episode\s*(\d+)", text, re.I)
    if m:
        return int(m.group(1))

    m = re.search(r"episode[-_ ]?(\d+)", filename, re.I)
    if m:
        return int(m.group(1))

    return 0


def parse_event_block(block: str) -> Event | None:
    """
    Parses blocks like:

    **CAMERA:**
    Start: (00:00.00) | End: (00:04.80)
    description

    or:

    **LADY JULIANA (Confused, Breathless):**
    Start: ...
    "Why?"
    """

    lines = [x.strip() for x in block.splitlines() if x.strip()]
    if not lines:
        return None

    header = lines[0]
    m_time = re.search(
        r"Start:\s*\(([^)]+)\)\s*\|\s*End:\s*\(([^)]+)\)",
        block,
        re.I,
    )
    if not m_time:
        return None

    start = time_to_seconds(m_time.group(1))
    end = time_to_seconds(m_time.group(2))
    if end <= start:
        return None

    header_clean = re.sub(r"^\*+\s*", "", header)
    header_clean = re.sub(r"\*+\s*$", "", header_clean).strip()

    kind = "action"
    speaker = ""
    delivery = ""

    if header_clean.upper().startswith("CAMERA"):
        kind = "camera"
    elif header_clean.upper().startswith("ACTION"):
        kind = "action"
    elif header_clean.upper().startswith("SOUND"):
        kind = "sound"
    else:
        # Character dialogue header:
        # LADY JULIANA (Confused, Breathless):
        kind = "dialogue"
        m = re.match(r"(.+?)\s*\((.*?)\)\s*:", header_clean)
        if m:
            speaker = clean_text(m.group(1))
            delivery = clean_text(m.group(2))
        else:
            speaker = header_clean.rstrip(":").strip()

    body = block[m_time.end():]
    body = re.sub(r"Start:\s*\([^)]+\)\s*\|\s*End:\s*\([^)]+\)", "", body)
    body = clean_text(body)
    body = body.strip('"')

    return Event(
        kind=kind,
        start=start,
        end=end,
        speaker=speaker,
        delivery=delivery,
        text=body,
    )


def parse_screenplay(text: str, filename: str) -> Episode:
    number = extract_episode_number(text, filename)

    name = filename
    m = re.search(r"EPISODE NUMBER:\s*(.+)", text, re.I)
    if m:
        name = clean_text(m.group(1))

    # Split on event headers. Each event block begins with **...:**
    chunks = re.split(r"(?=^\*\*[^*\n]+:\*\*\s*$)", text, flags=re.M)

    events: list[Event] = []

    for chunk in chunks:
        event = parse_event_block(chunk)
        if event:
            events.append(event)

    events.sort(key=lambda e: (e.start, e.end))

    return Episode(
        number=number,
        name=name,
        text=text,
        events=events,
    )


def load_uploaded_files(files: list[Any]) -> tuple[list[Episode], list[dict[str, Any]]]:
    episodes: list[Episode] = []
    report: list[dict[str, Any]] = []

    for uploaded in files:
        filename = getattr(uploaded, "name", "uploaded.txt")
        try:
            raw = uploaded.getvalue()

            if filename.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    for member in z.namelist():
                        if member.lower().endswith(".txt") and not member.endswith("/"):
                            content = z.read(member).decode("utf-8", errors="replace")
                            ep = parse_screenplay(content, Path(member).name)
                            if ep.events:
                                episodes.append(ep)
                                report.append({
                                    "file": member,
                                    "status": "ok",
                                    "warnings": "",
                                })
                            else:
                                report.append({
                                    "file": member,
                                    "status": "skipped",
                                    "warnings": "No timed screenplay events found.",
                                })
            else:
                content = raw.decode("utf-8", errors="replace")
                ep = parse_screenplay(content, filename)
                if ep.events:
                    episodes.append(ep)
                    report.append({
                        "file": filename,
                        "status": "ok",
                        "warnings": "",
                    })
                else:
                    report.append({
                        "file": filename,
                        "status": "skipped",
                        "warnings": "No timed screenplay events found.",
                    })

        except Exception as exc:
            report.append({
                "file": filename,
                "status": "error",
                "warnings": f"{type(exc).__name__}: {exc}",
            })

    episodes.sort(key=lambda x: x.number)
    return episodes, report


def load_folder(folder: str) -> tuple[list[Episode], list[dict[str, Any]]]:
    path = Path(folder)

    if not path.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")

    if path.is_file() and path.suffix.lower() == ".zip":
        with path.open("rb") as f:
            class LocalUpload:
                def __init__(self, name: str, data: bytes):
                    self.name = name
                    self._data = data

                def getvalue(self):
                    return self._data

            return load_uploaded_files([LocalUpload(path.name, f.read())])

    files = sorted(path.rglob("*.txt"))
    uploads = []

    for file in files:
        uploads.append(
            type(
                "LocalUpload",
                (),
                {
                    "name": file.name,
                    "getvalue": lambda f=file: f.read_bytes(),
                },
            )()
        )

    return load_uploaded_files(uploads)


# ---------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------

def camera_shots(events: list[Event]) -> list[Event]:
    shots = [e for e in events if e.kind == "camera"]
    shots.sort(key=lambda x: x.start)
    return shots


def dialogue_events(events: list[Event]) -> list[Event]:
    return sorted(
        [e for e in events if e.kind == "dialogue"],
        key=lambda x: x.start,
    )


def action_events(events: list[Event]) -> list[Event]:
    return sorted(
        [e for e in events if e.kind == "action"],
        key=lambda x: x.start,
    )


def make_candidates(ep: Episode) -> list[dict[str, Any]]:
    shots = camera_shots(ep.events)

    # If camera blocks are unavailable, fall back to timed events.
    if not shots:
        shots = [
            Event("camera", e.start, e.end, text=e.text)
            for e in ep.events
            if e.kind in ("action", "dialogue")
        ]

    candidates: list[dict[str, Any]] = []

    for i, start_shot in enumerate(shots):
        start = start_shot.start

        # A valid promo should have meaningful content within first 3 sec.
        early_content = [
            e for e in ep.events
            if e.kind in ("dialogue", "action")
            and start <= e.start <= start + 3.0
        ]

        if not early_content:
            continue

        for end_shot in shots[i:]:
            end = end_shot.end
            duration = end - start

            if duration < 20:
                continue

            if duration > 60:
                break

            # Avoid cuts that occur while a dialogue line is still active.
            split_dialogue = any(
                d.start < end < d.end - 0.05
                for d in dialogue_events(ep.events)
            )

            if split_dialogue:
                continue

            inside = [
                e for e in ep.events
                if e.start >= start - 0.01 and e.end <= end + 0.01
                and e.kind in ("dialogue", "action")
            ]

            if not inside:
                continue

            candidates.append({
                "start": start,
                "end": end,
                "duration": duration,
                "events": inside,
                "episode": ep,
            })

    # Deduplicate identical start/end pairs.
    seen = set()
    unique = []

    for c in candidates:
        key = (round(c["start"], 2), round(c["end"], 2))
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique


# ---------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------

HOOK_WORDS = {
    "what", "why", "who", "how", "wait", "stop", "please", "help",
    "no", "never", "listen", "you", "she", "he", "they", "betray",
    "dead", "marry", "married", "leave", "leaving", "secret", "truth",
    "kill", "killed", "danger", "sorry", "wrong",
}

TENSION_WORDS = {
    "threat", "danger", "kill", "dead", "betray", "betrayed", "lie",
    "secret", "blood", "police", "fight", "cry", "fear", "afraid",
    "leave", "run", "escape", "trap", "revenge", "divorce", "wedding",
}

CLIFF_WORDS = {
    "but", "however", "wait", "why", "what", "who", "how", "never",
    "unless", "because", "truth", "secret", "tomorrow", "tonight",
    "before", "after", "really", "actually", "know", "knew",
}


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text.lower()))


def keyword_score(text: str, words: set[str]) -> float:
    tokens = set(re.findall(r"\b[\w']+\b", text.lower()))
    if not tokens:
        return 0.0
    return min(1.0, len(tokens & words) / 3.0)


def score_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    ep: Episode = candidate["episode"]
    start = candidate["start"]
    end = candidate["end"]

    events = candidate["events"]
    dialogs = [e for e in events if e.kind == "dialogue"]

    first_content = min(events, key=lambda e: e.start)
    hook_text = first_content.text

    # Look shortly after the cut to identify withheld information.
    after = [
        e for e in ep.events
        if e.start >= end - 0.01
        and e.start <= end + 8.0
        and e.kind in ("dialogue", "action")
    ]

    after_text = " ".join(e.text for e in after[:3])

    # Hook: 25
    hook_base = keyword_score(hook_text, HOOK_WORDS)
    hook_length = word_count(hook_text)
    hook = 12.0 + 10.0 * hook_base
    if hook_length >= 3:
        hook += 3.0
    hook = min(25.0, hook)

    # Cliffhanger: 30
    last_text = dialogs[-1].text if dialogs else events[-1].text
    cliff = 10.0
    if "?" in last_text:
        cliff += 10.0
    if keyword_score(last_text, CLIFF_WORDS) > 0:
        cliff += 5.0
    if after_text and keyword_score(after_text, CLIFF_WORDS) > 0:
        cliff += 5.0
    cliff = min(30.0, cliff)

    # Standalone: 15
    standalone = 15.0
    if len(events) < 3:
        standalone -= 5.0
    if not dialogs:
        standalone -= 4.0
    standalone = max(0.0, standalone)

    # Tension: 20
    combined = " ".join(e.text for e in events)
    tension = 8.0 + 12.0 * keyword_score(combined, TENSION_WORDS)
    tension = min(20.0, tension)

    # Pace: 10
    duration = candidate["duration"]
    density = word_count(combined) / max(duration, 1.0)

    if 1.2 <= density <= 3.5:
        pace = 10.0
    elif 0.6 <= density < 1.2 or 3.5 < density <= 5:
        pace = 7.0
    else:
        pace = 4.0

    total = round(hook + cliff + standalone + tension + pace, 2)

    flags = []

    if duration < 20 or duration > 60:
        flags.append("duration outside 20–60 s")

    if not dialogs:
        flags.append("no dialogue")

    if len(events) < 3:
        flags.append("limited scene context")

    why_parts = []

    if hook >= 20:
        why_parts.append("strong opening hook")
    elif hook >= 16:
        why_parts.append("clear opening setup")

    if cliff >= 22:
        why_parts.append("strong cliffhanger")
    elif cliff >= 17:
        why_parts.append("curiosity at the ending")

    if tension >= 15:
        why_parts.append("high emotional tension")

    if not why_parts:
        why_parts.append("coherent short narrative segment")

    return {
        "episode": ep.number,
        "start": start,
        "end": end,
        "start_ts": seconds_to_ts(start),
        "end_ts": seconds_to_ts(end),
        "duration": round(duration, 2),
        "hook": hook_text,
        "cliffhanger": last_text,
        "cut_before": after_text[:300],
        "why": ", ".join(why_parts).capitalize() + ".",
        "score": total,
        "parts": {
            "hook": round(hook, 2),
            "cliffhanger": round(cliff, 2),
            "standalone": round(standalone, 2),
            "tension": round(tension, 2),
            "pace": round(pace, 2),
        },
        "flags": flags,
        "transcript": [
            {
                "t": round(e.start, 2),
                "speaker": e.speaker,
                "delivery": e.delivery,
                "line": e.text,
            }
            for e in events
        ],
    }


def rank_promos(
    episodes: list[Episode],
    per_episode: int,
    recommended: int,
) -> tuple[list[dict[str, Any]], int]:
    all_candidates = []
    total_candidates = 0

    for ep in episodes:
        candidates = make_candidates(ep)
        total_candidates += len(candidates)

        scored = [score_candidate(c) for c in candidates]
        scored.sort(key=lambda x: x["score"], reverse=True)

        # Avoid highly overlapping picks.
        selected: list[dict[str, Any]] = []

        for p in scored:
            too_much_overlap = False

            for q in selected:
                overlap = max(
                    0.0,
                    min(p["end"], q["end"]) - max(p["start"], q["start"]),
                )
                shorter = min(
                    p["end"] - p["start"],
                    q["end"] - q["start"],
                )

                if shorter > 0 and overlap / shorter > 0.25:
                    too_much_overlap = True
                    break

            if not too_much_overlap:
                selected.append(p)

            if len(selected) >= per_episode:
                break

        all_candidates.extend(selected)

    all_candidates.sort(key=lambda x: x["score"], reverse=True)

    for idx, promo in enumerate(all_candidates, start=1):
        promo["rank"] = idx
        promo["recommended"] = "yes" if idx <= recommended else "no"

    return all_candidates, total_candidates


# ---------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------

def flatten_promos(promos: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []

    for p in promos:
        rows.append({
            "rank": p["rank"],
            "recommended": p["recommended"],
            "episode": p["episode"],
            "start": p["start_ts"],
            "end": p["end_ts"],
            "duration": p["duration"],
            "score": p["score"],
            "hook": p["hook"],
            "cliffhanger": p["cliffhanger"],
            "cut_before": p["cut_before"],
            "why": p["why"],
            "hook_score": p["parts"]["hook"],
            "cliffhanger_score": p["parts"]["cliffhanger"],
            "standalone_score": p["parts"]["standalone"],
            "tension_score": p["parts"]["tension"],
            "pace_score": p["parts"]["pace"],
            "flags": "; ".join(p["flags"]),
        })

    return pd.DataFrame(rows)


def markdown_report(promos: list[dict[str, Any]]) -> str:
    lines = [
        "# Kuku Promo Finder — Ranked Promos",
        "",
    ]

    for p in promos:
        lines.extend([
            f"## #{p['rank']} — Episode {p['episode']} — {p['score']:.1f} points",
            f"- Time: `{p['start_ts']}–{p['end_ts']}`",
            f"- Duration: `{p['duration']:.1f}s`",
            f"- Recommended: `{p['recommended']}`",
            f"- Hook: {p['hook']}",
            f"- Cliffhanger: {p['cliffhanger']}",
            f"- Cut before: {p['cut_before'] or '(episode ends)'}",
            f"- Why it works: {p['why']}",
            "",
        ])

    return "\n".join(lines)


# ---------------------------------------------------------------------
# Cached analysis
# ---------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def analyze_uploaded(
    file_payloads: tuple,
    per_episode: int,
    recommended: int,
):
    class MemoryUpload:
        def __init__(self, name, data):
            self.name = name
            self._data = data

        def getvalue(self):
            return self._data

    uploads = [MemoryUpload(name, data) for name, data in file_payloads]
    episodes, report = load_uploaded_files(uploads)
    promos, candidate_count = rank_promos(
        episodes,
        per_episode,
        recommended,
    )

    return episodes, report, promos, candidate_count


# ---------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------

with st.sidebar:
    st.header("1 · Input")

    mode = st.radio(
        "Where are the screenplays?",
        ["Upload files", "Folder on this machine"],
        index=0,
    )

    folder = ""
    uploads = []

    if mode == "Upload files":
        files = st.file_uploader(
            "Upload screenplay .txt files or one .zip",
            type=["txt", "zip"],
            accept_multiple_files=True,
        )
        uploads = files or []

    else:
        folder = st.text_input(
            "Folder or .zip path",
            value="data/raw",
        )

    st.header("2 · Settings")

    per_episode = st.slider(
        "Promos kept per episode",
        min_value=1,
        max_value=5,
        value=3,
    )

    recommended = st.slider(
        "Mark top N as 'post first'",
        min_value=1,
        max_value=50,
        value=15,
    )

    st.header("3 · Judge")

    st.info(
        "This corrected standalone version uses a deterministic heuristic "
        "judge and does not require an external LLM API."
    )

    run_button = st.button(
        "▶ Run Analysis",
        type="primary",
        width="stretch",
    )


# ---------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------

if not uploads and not folder:
    st.info(
        "Upload screenplay files or select a local folder to begin."
    )
    st.stop()


try:
    if uploads:
        payloads = tuple(
            (f.name, f.getvalue())
            for f in uploads
        )

        with st.spinner("Parsing screenplays and scoring promo windows..."):
            episodes, report, promos, candidate_count = analyze_uploaded(
                payloads,
                per_episode,
                recommended,
            )

    else:
        if not run_button and not st.session_state.get("folder_result"):
            st.info("Enter the folder path and click **Run Analysis**.")
            st.stop()

        if run_button or "folder_result" not in st.session_state:
            with st.spinner("Parsing screenplays and scoring promo windows..."):
                episodes, report = load_folder(folder)
                promos, candidate_count = rank_promos(
                    episodes,
                    per_episode,
                    recommended,
                )
                st.session_state["folder_result"] = (
                    episodes,
                    report,
                    promos,
                    candidate_count,
                )
        else:
            episodes, report, promos, candidate_count = (
                st.session_state["folder_result"]
            )

except Exception as exc:
    st.error(
        f"Something went wrong while processing: "
        f"{type(exc).__name__}: {exc}"
    )
    st.exception(exc)
    st.stop()


# ---------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------

if not episodes:
    st.warning("No readable screenplay episodes were found.")
    st.stop()

if not promos:
    st.warning(
        "No promo windows were found. "
        "The episodes may be shorter than 20 seconds or may not contain "
        "enough timed screenplay events."
    )
    st.stop()


passed = all(
    not p["flags"]
    for p in promos
)

c1, c2, c3, c4 = st.columns(4)

c1.metric("Episodes", len(episodes))
c2.metric("Windows scored", f"{candidate_count:,}")
c3.metric("Promos ranked", len(promos))
c4.metric(
    "Quality checks",
    "Passed ✅" if passed else "Review ⚠️",
)

bad_files = [
    r for r in report
    if r["status"] in ("error", "skipped")
]

for r in bad_files:
    st.warning(
        f"{r['status'].upper()}: {r['file']} — {r['warnings']}"
    )


tab_rank, tab_view, tab_quality, tab_run = st.tabs(
    [
        "🏆 Ranked Promos",
        "🔍 Inspect a Promo",
        "✅ Quality",
        "ℹ️ Run Details",
    ]
)


# ---------------------------------------------------------------------
# Ranked promos
# ---------------------------------------------------------------------

flat = flatten_promos(promos)

with tab_rank:
    f1, f2 = st.columns(2)

    selected_eps = f1.multiselect(
        "Episodes",
        sorted(flat["episode"].unique()),
    )

    only_recommended = f2.checkbox(
        "Only 'post first'",
        value=False,
    )

    view = flat.copy()

    if selected_eps:
        view = view[
            view["episode"].isin(selected_eps)
        ]

    if only_recommended:
        view = view[
            view["recommended"] == "yes"
        ]

    st.dataframe(
        view,
        hide_index=True,
        width="stretch",
    )

    d1, d2, d3 = st.columns(3)

    d1.download_button(
        "⬇ Download CSV",
        flat.to_csv(index=False).encode("utf-8-sig"),
        "promos_ranked.csv",
        "text/csv",
    )

    d2.download_button(
        "⬇ Download JSON",
        json.dumps(
            promos,
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8"),
        "promos_ranked.json",
        "application/json",
    )

    d3.download_button(
        "⬇ Download Markdown",
        markdown_report(promos).encode("utf-8"),
        "promos_ranked.md",
        "text/markdown",
    )


# ---------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------

with tab_view:
    labels = {
        f"#{p['rank']} · EP{p['episode']:02d} · "
        f"{p['start_ts']}–{p['end_ts']} · "
        f"{p['score']:.1f} pts": p
        for p in promos
    }

    selected = st.selectbox(
        "Select a promo",
        list(labels.keys()),
    )

    p = labels[selected]

    st.subheader(
        f"Episode {p['episode']} — "
        f"{p['start_ts']}–{p['end_ts']} "
        f"({p['duration']:.1f}s)"
    )

    st.write(
        f"**Why it works:** {p['why']}"
    )

    a, b = st.columns(2)

    a.success(
        f"**Hook**\n\n{p['hook']}"
    )

    b.warning(
        f"**Cliffhanger**\n\n"
        f"{p['cliffhanger']}\n\n"
        f"**Cut before:** "
        f"{p['cut_before'] or '(episode ends)'}"
    )

    if p["flags"]:
        st.error(
            "Check before posting: "
            + "; ".join(p["flags"])
        )

    st.subheader("Score Breakdown")

    score_df = pd.DataFrame({
        "Category": [
            "Hook",
            "Cliffhanger",
            "Standalone",
            "Tension",
            "Pace",
        ],
        "Points": [
            p["parts"]["hook"],
            p["parts"]["cliffhanger"],
            p["parts"]["standalone"],
            p["parts"]["tension"],
            p["parts"]["pace"],
        ],
    })

    st.bar_chart(
        score_df.set_index("Category")
    )

    st.subheader("Transcript")

    transcript_rows = []

    for i, row in enumerate(p["transcript"]):
        role = ""

        if i == 0:
            role = "🎣 Hook"

        if i == len(p["transcript"]) - 1:
            role = "🧗 Cliffhanger"

        transcript_rows.append({
            "Time": seconds_to_ts(row["t"]),
            "Role": role,
            "Speaker": row["speaker"],
            "Delivery": row["delivery"],
            "Line": row["line"],
        })

    st.dataframe(
        pd.DataFrame(transcript_rows),
        hide_index=True,
        width="stretch",
    )

    st.caption(
        "Timestamps are screenplay timestamps. "
        "The application analyzes screenplay text; an editor must watch "
        "the actual video before publishing the cut."
    )


# ---------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------

with tab_quality:
    quality_rows = []

    for p in promos:
        quality_rows.append({
            "Rank": p["rank"],
            "Episode": p["episode"],
            "Duration 20–60s": 20 <= p["duration"] <= 60,
            "Has hook": bool(p["hook"]),
            "Has ending": bool(p["cliffhanger"]),
            "No flags": len(p["flags"]) == 0,
            "Score": p["score"],
        })

    quality_df = pd.DataFrame(quality_rows)

    st.dataframe(
        quality_df,
        hide_index=True,
        width="stretch",
    )

    st.write(
        "The quality checks shown here are deterministic checks based "
        "on the screenplay data."
    )


# ---------------------------------------------------------------------
# Run details
# ---------------------------------------------------------------------

with tab_run:
    st.json({
        "episodes": len(episodes),
        "candidate_windows_scored": candidate_count,
        "promos_ranked": len(promos),
        "judge": "heuristic",
        "per_episode": per_episode,
        "recommended_top_n": recommended,
    })

    st.subheader("Parse Report")

    st.dataframe(
        pd.DataFrame(report),
        hide_index=True,
        width="stretch",
    )
