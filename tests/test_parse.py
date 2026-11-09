import zipfile

import pytest

from promo_finder.parse import load_inputs, load_uploaded, parse_text, parse_ts

GOOD = """EPISODE NUMBER: Episode 7
EPISODE LOGLINE: A test.
CONTINUITY NOTES: Picks up directly from Episode 6's cliffhanger where a door opens.

--- SCRIPT START ---

SCENE 01
Scene heading: INT. ROOM - DAY
Scene start: 00:00.00
Scene end: 00:30.00

Actions and dialogue:

**CAMERA:**
Start: (00:00.00) | End: (00:05.00)
Wide shot.

**LADY ANNA (Cold, Furious):**
Start: (00:01.00) | End: (00:03.00)
"Leave. Now."

**GERALD (O.S.) (Smug):**
Start: (00:03.50) | End: (00:05.00)
"Make me."

**ALEXANDER (V.O.) (Haunted):**
Start: (00:06.00) | End: (00:08.00)
"One blow would end this."

**SOUND FX:**
Start: (00:09.00) | End: (00:30.50)
A door slams.
--- SCRIPT END ---
"""


def test_timestamp_variants():
    assert parse_ts("01:23.45") == pytest.approx(83.45)
    assert parse_ts("(00:07)") == 7
    assert parse_ts("1:02:03.5") == pytest.approx(3723.5)
    with pytest.raises(ValueError):
        parse_ts("soon")


def test_parse_dialogue_tags_markers_and_metadata():
    ep = parse_text(GOOD, "episode-007.txt")
    assert ep.number == 7 and ep.logline == "A test."
    d = ep.dialogue
    assert [x.speaker for x in d] == ["LADY ANNA", "GERALD", "ALEXANDER"]
    assert d[0].tags == ("cold", "furious") and d[0].who == "ANNA"  # honorific dropped for counting
    assert d[1].offscreen and not d[1].voiceover and d[1].tags == ("smug",)
    assert d[2].voiceover
    assert d[0].text == "Leave. Now."  # quotes stripped
    kinds = {e.kind for e in ep.events}
    assert kinds == {"CAMERA", "DIALOGUE", "SOUND_FX"}


def test_overshoot_is_flagged_not_fixed():
    ep = parse_text(GOOD, "x.txt")
    assert any("after scene end" in w for w in ep.warnings)
    assert max(e.end for e in ep.events) == 30.5


def test_crlf_and_bom():
    ep = parse_text("\ufeff" + GOOD.replace("\n", "\r\n"), "e.txt")
    assert len(ep.dialogue) == 3


def test_header_without_timing_is_skipped_with_warning():
    broken = GOOD.replace("Start: (00:03.50) | End: (00:05.00)", "")
    ep = parse_text(broken, "e.txt")
    assert len(ep.dialogue) == 2
    assert any("no Start/End" in w for w in ep.warnings)


def test_non_positive_duration_skipped():
    bad = GOOD.replace("Start: (00:01.00) | End: (00:03.00)", "Start: (00:03.00) | End: (00:01.00)")
    ep = parse_text(bad, "e.txt")
    assert any("non-positive" in w for w in ep.warnings)


def test_not_a_screenplay_raises():
    with pytest.raises(ValueError):
        parse_text("just some notes\nnothing timed", "notes.txt")


def test_episode_number_from_filename_fallback():
    text = GOOD.replace("EPISODE NUMBER: Episode 7\n", "")
    assert parse_text(text, "episode-012-abc.txt").number == 12


def test_load_inputs_survives_bad_and_duplicate_files(tmp_path):
    (tmp_path / "episode-001.txt").write_text(GOOD.replace("Episode 7", "Episode 1"), encoding="utf-8")
    (tmp_path / "dup.txt").write_text(GOOD.replace("Episode 7", "Episode 1"), encoding="utf-8")
    (tmp_path / "readme.txt").write_text("hello", encoding="utf-8")
    eps, rep = load_inputs(tmp_path)
    assert [e.number for e in eps] == [1]
    statuses = {r["file"]: r["status"] for r in rep}
    assert statuses["readme.txt"] == "error"
    # files load in alphabetical order; the first claim on an episode number wins, the other is reported
    assert sorted([statuses["dup.txt"], statuses["episode-001.txt"]]) == ["ok_with_warnings", "skipped"]


def test_zip_and_uploads(tmp_path, sample_dir):
    z = tmp_path / "pack.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in sorted(sample_dir.glob("*.txt")):
            zf.write(f, f.name)
    eps, _ = load_inputs(z)
    assert len(eps) == 3
    files = [(f.name, f.read_bytes()) for f in sorted(sample_dir.glob("*.txt"))]
    eps2, _ = load_uploaded(files)
    assert [e.number for e in eps2] == [1, 2, 3]


def test_missing_path():
    with pytest.raises(FileNotFoundError):
        load_inputs("/definitely/not/here")
