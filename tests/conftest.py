import shutil
from pathlib import Path

import pytest


@pytest.fixture
def work(tmp_path: Path) -> Path:
    return tmp_path
