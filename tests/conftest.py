import os
import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore", category=DeprecationWarning)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own job store / settings directory and no cloud credentials."""
    monkeypatch.setenv("QP_HOME", str(tmp_path / "qplay_home"))
    for var in ("QP_IBM_TOKEN", "QISKIT_IBM_TOKEN", "IBM_QUANTUM_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    from quantum_playground import config
    config.clear_session_ibm_credentials()
    monkeypatch.setattr(config, "_DOTENV_LOADED", True)
    yield
