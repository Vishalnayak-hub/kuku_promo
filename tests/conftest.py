import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from promo_finder.parse import load_inputs  # noqa: E402


@pytest.fixture(scope="session")
def sample_dir():
    return ROOT / "sample_data"


@pytest.fixture(scope="session")
def sample_episodes(sample_dir):
    eps, _ = load_inputs(sample_dir)
    return eps
