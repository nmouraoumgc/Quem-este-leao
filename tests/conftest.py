from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quem_e_este_leao.config import Settings  # noqa: E402
from quem_e_este_leao.logging_setup import setup_logging  # noqa: E402

setup_logging("DEBUG")


@pytest.fixture()
def project_root() -> Path:
    return ROOT


@pytest.fixture()
def tmp_settings(tmp_path: Path, project_root: Path) -> Settings:
    db_path = tmp_path / "test.sqlite3"
    out = tmp_path / "out"
    preview = tmp_path / "preview"
    out.mkdir()
    preview.mkdir()
    return Settings(
        _env_file=None,
        database_path=db_path,
        players_yaml=project_root / "data" / "players.yaml",
        output_dir=out,
        preview_dir=preview,
        assets_dir=project_root / "assets",
        dry_run=True,
        wikimedia_enabled=False,
        abort_if_recognizable=False,
        ocr_enabled=False,
    )
