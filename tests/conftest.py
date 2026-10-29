"""Shared test fixtures.

Every test runs against a throwaway configuration directory so the real
``%APPDATA%\\IDFA\\config.yaml`` and the user's case data are never touched.
The environment variable is set at import time, before any ``app`` module
reads the configuration path.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

# Must happen before app.config is imported anywhere in the test session.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IDFA_CONFIG_DIR"] = str(
    Path(tempfile.mkdtemp(prefix="idfa_pytest_settings_")) / "config"
)


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    """Point ``app.config`` at an empty per-test configuration directory."""
    from app import config as config_module

    home = tmp_path / "config"
    monkeypatch.setenv("IDFA_CONFIG_DIR", str(home))
    config_module.clear_config_cache()
    yield home
    config_module.clear_config_cache()


@pytest.fixture
def data_dir(tmp_path):
    """An existing, writable data root."""
    root = tmp_path / "data"
    root.mkdir()
    return root


@pytest.fixture(scope="session")
def qt_app():
    """One QApplication for the whole session; widgets need it to exist."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
