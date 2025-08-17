import os
import threading
from typing import Optional

# Lazy import to avoid import-time heavy loads
_RouterType = None  # type: ignore
_router_singleton: Optional[object] = None
_router_lock = threading.Lock()


def _intent_enabled() -> bool:
    v = os.getenv("INTENT_ENABLED", "true").strip().lower()
    return v not in ("0", "false", "no")


def get_router() -> Optional[object]:
    """Return a process-wide Router singleton or None if disabled.
    This avoids reloading HanLP/resources on every request.
    """
    if not _intent_enabled():
        return None

    global _router_singleton, _RouterType
    if _router_singleton is not None:
        return _router_singleton

    with _router_lock:
        if _router_singleton is None:
            # Resolve Router type lazily
            if _RouterType is None:
                from .slot_pipeline import Router as _R  # type: ignore
                _RouterType = _R
            _router_singleton = _RouterType()  # type: ignore
    return _router_singleton


def warmup() -> bool:
    """Proactively build the singleton; return True if ready."""
    return get_router() is not None 