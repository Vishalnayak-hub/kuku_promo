import json
import subprocess
import sys
from pathlib import Path

from promo_finder.cli import main
from promo_finder.evaluate import hard_checks
from promo_finder.parse import load_inputs
from promo_finder.pipeline import RunConfig, run

ROOT = Path(__file__).resolve().parent.parent


def test_run_produces_valid_ranked_promos(sample_episodes):
    res = run(sample_episodes, RunConfig())
    assert res.promos and [p["rank"] for p in res.promos] == list(range(1, len(res.promos) + 1))
    assert all(c["passed"] for c in hard_checks(res.promos, sample_episodes))
    for p in res.promos:
        assert p["segments"] and p["hook"] and p["why"]
        assert set(p["parts"]) == {"hook", "cliffhanger", "standalone", "tension", "pace"}


def test_cli_writes_every_output_and_is_deterministic(tmp_path, sample_dir):
    a, b = tmp_path / "a", tmp_path / "b"
    assert main(["run", "-i", str(sample_dir), "-o", str(a), "-q"]) == 0
    assert main(["run", "-i", str(sample_dir), "-o", str(b), "-q"]) == 0
    for name in ("promos_ranked.csv", "promos_ranked.json", "promos_ranked.md", "parse_report.csv",
                 "quality_report.md", "quality_report.json", "run_summary.json"):
        assert (a / name).exists(), name
    assert (a / "promos_ranked.json").read_text("utf-8") == (b / "promos_ranked.json").read_text("utf-8")
    assert json.loads((a / "run_summary.json").read_text("utf-8"))["hard_checks_passed"] is True


def test_cli_friendly_errors(tmp_path, capsys):
    assert main(["run", "-i", str(tmp_path / "nope"), "-o", str(tmp_path / "o"), "-q"]) == 2
    assert "not found" in capsys.readouterr().err
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "junk.txt").write_text("not a screenplay", encoding="utf-8")
    assert main(["run", "-i", str(empty), "-o", str(tmp_path / "o2"), "-q"]) == 2


def test_one_bad_file_does_not_abort_the_run(tmp_path, sample_dir):
    for f in sample_dir.glob("*.txt"):
        (tmp_path / f.name).write_text(f.read_text("utf-8"), encoding="utf-8")
    (tmp_path / "broken.txt").write_text("garbage", encoding="utf-8")
    assert main(["run", "-i", str(tmp_path), "-o", str(tmp_path / "out"), "-q"]) == 0
    summary = json.loads((tmp_path / "out" / "run_summary.json").read_text("utf-8"))
    assert summary["episodes"] == 3 and summary["parse_errors"]


def test_module_entrypoint_runs(tmp_path, sample_dir):
    r = subprocess.run([sys.executable, "-m", "promo_finder", "run", "-i", str(sample_dir),
                        "-o", str(tmp_path / "o"), "-q"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_stitch_flag_runs_and_stays_valid(sample_episodes, monkeypatch):
    from promo_finder import stitch
    monkeypatch.setattr(stitch, "PENALTY", -100.0)          # force the join to win, to test the plumbing
    monkeypatch.setattr(stitch, "MIN_HOOK_ADVANTAGE", -100.0)
    res = run(sample_episodes, RunConfig(stitch=True))
    stitched = [p for p in res.promos if p["stitched"]]
    assert stitched, "forced stitch should produce at least one promo"
    for p in stitched:
        assert len(p["segments"]) == 2 and p["needs_editor_check"]
        a, b = p["segments"]
        assert b["start"] >= a["end"] + 2.0 - 1e-6 and 20 <= p["duration"] <= 60
    assert all(c["passed"] for c in hard_checks(res.promos, sample_episodes))


def test_real_pack_if_present():
    pack = ROOT / "data" / "raw"
    if not pack.is_dir() or not list(pack.glob("*.txt")):
        return
    eps, _ = load_inputs(pack)
    res = run(eps, RunConfig())
    assert len(eps) == 50 and all(c["passed"] for c in hard_checks(res.promos, eps))


def test_dotenv_loader_does_not_override_and_ignores_junk(tmp_path, monkeypatch):
    from promo_finder.envfile import load_dotenv
    f = tmp_path / ".env"
    f.write_text("# comment\n\nLLM_MODEL='my-model'\nexport LLM_API_KEY=abc\nBROKEN LINE\nKEEP=new\n", encoding="utf-8")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("KEEP", "old")
    assert sorted(load_dotenv(f)) == ["LLM_API_KEY", "LLM_MODEL"]
    import os
    assert os.environ["LLM_MODEL"] == "my-model" and os.environ["KEEP"] == "old"
    assert load_dotenv(tmp_path / "missing.env") == []
