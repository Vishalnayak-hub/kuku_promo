import shutil
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def app_dir(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "sample_data", tmp_path / "sample_data")
    monkeypatch.chdir(tmp_path)      # default_folder() must find the bundled sample, not a local data/raw
    return tmp_path


def _metrics(at):
    return {m.label: m.value for m in at.metric}


def test_app_loads_sample_and_shows_everything(app_dir):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    m = _metrics(at)
    assert m["Episodes"] == "3" and "passed" in m["Hard checks"]
    assert len(at.tabs) == 4 and len(at.dataframe) >= 3
    assert not at.error


def test_app_inspector_selects_a_promo(app_dir):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    at.selectbox[0].select_index(1).run()
    assert not at.exception, at.exception


def test_app_bad_folder_shows_error_not_traceback(app_dir):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    at.text_input[0].set_value("/definitely/not/here").run()
    assert not at.exception
    assert any("not found" in e.value.lower() for e in at.error)


def test_llm_mode_waits_for_run_and_validates_model(app_dir):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    at.radio[1].set_value("LLM re-ranking (needs an API key)").run()
    assert not at.exception
    assert any("press **Run**" in i.value or "press Run" in i.value for i in at.info)   # nothing sent yet
    at.button[0].click().run()                                                        # no model name entered
    assert any("model name" in e.value.lower() for e in at.error)
