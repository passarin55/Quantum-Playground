"""Settings and credential resolution.

Credentials are **never** written into the project tree by this program.
Resolution order for IBM Quantum:

1. a token set for the current process only (web studio "use for this session"),
2. environment variables ``QP_IBM_TOKEN`` (or ``QISKIT_IBM_TOKEN`` / ``IBM_QUANTUM_TOKEN``),
3. a ``.env`` file in the working directory or in ``$QP_HOME`` (git-ignored),
4. an account saved with ``qplay ibm login --save`` / ``QiskitRuntimeService.save_account``
   (stored by Qiskit in ``~/.qiskit/qiskit-ibm.json``, outside the repo).
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_LOCK = threading.Lock()
_SESSION: dict[str, str] = {}
_DOTENV_LOADED = False


def qplay_home() -> Path:
    home = Path(os.environ.get("QP_HOME") or Path.home() / ".qplay")
    home.mkdir(parents=True, exist_ok=True)
    return home


def _parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v:
                out[k.strip()] = v
    except OSError:
        pass
    return out


def load_dotenv() -> None:
    """Populate os.environ from .env files without overriding existing variables."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    for p in (Path.cwd() / ".env", qplay_home() / ".env"):
        for k, v in _parse_dotenv(p).items():
            os.environ.setdefault(k, v)
    _DOTENV_LOADED = True


@dataclass(frozen=True)
class IBMCredentials:
    token: Optional[str] = None
    instance: Optional[str] = None
    channel: str = "ibm_quantum_platform"
    source: str = "none"

    @property
    def masked(self) -> str:
        if not self.token:
            return "(none)"
        return self.token[:3] + "…" + self.token[-3:] if len(self.token) > 8 else "…"

    def describe(self) -> dict:
        return {"source": self.source, "token": self.masked, "instance": self.instance or "(auto)",
                "channel": self.channel}


def set_session_ibm_credentials(token: Optional[str], instance: Optional[str] = None,
                                channel: Optional[str] = None) -> None:
    with _LOCK:
        _SESSION.clear()
        if token:
            _SESSION["token"] = token.strip()
        if instance:
            _SESSION["instance"] = instance.strip()
        if channel:
            _SESSION["channel"] = channel.strip()


def clear_session_ibm_credentials() -> None:
    with _LOCK:
        _SESSION.clear()


def ibm_credentials() -> IBMCredentials:
    load_dotenv()
    with _LOCK:
        if _SESSION.get("token"):
            return IBMCredentials(_SESSION["token"], _SESSION.get("instance"),
                                  _SESSION.get("channel", "ibm_quantum_platform"), "session")
    for var in ("QP_IBM_TOKEN", "QISKIT_IBM_TOKEN", "IBM_QUANTUM_TOKEN"):
        tok = os.environ.get(var)
        if tok:
            return IBMCredentials(tok, os.environ.get("QP_IBM_INSTANCE") or os.environ.get("QISKIT_IBM_INSTANCE"),
                                  os.environ.get("QP_IBM_CHANNEL", "ibm_quantum_platform"), f"env:{var}")
    return IBMCredentials(None, os.environ.get("QP_IBM_INSTANCE"),
                          os.environ.get("QP_IBM_CHANNEL", "ibm_quantum_platform"), "saved-account")


def default_ibm_backend() -> Optional[str]:
    load_dotenv()
    return os.environ.get("QP_IBM_BACKEND") or None


def package_available(name: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False
