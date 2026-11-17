"""sample_writer — generate realistic fake platform downloads from real ones.

    python -m sample_writer                  # in/ -> out/
    python -m sample_writer --platform sms   # one platform
    python -m sample_writer clean
    python -m sample_writer capture          # in/ -> schemas/

All knobs live in `config.py`.
"""
from __future__ import annotations

__all__ = ["build", "clean", "config"]

from .config import IN_DIR, OUT_DIR, PLATFORMS, SEED, VARIANTS  # noqa: F401


def __getattr__(name: str):
    """`build` and `clean` live in `__main__`; import lazily so `python -m` is clean."""
    if name in {"build", "clean"}:
        from . import __main__ as runner
        return getattr(runner, name)
    raise AttributeError(name)
