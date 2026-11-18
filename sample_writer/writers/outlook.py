"""Outlook. Not synthesizable in pure Python — copy the committed fixture.

`tests/fixtures/outlook/Outlook.pst` is the Aspose sample mailbox: 11 demo messages from
2011, no real correspondence. Building a `.pst` by hand would be a lie dressed up as a
sample, so this writer copies instead of generates.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from random import Random

from .. import config
from ..plan import Plan
from ..world import World

KIND = "outlook"
FIXTURE = (Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "outlook"
           / "Outlook.pst")


def write_copy(plan: Plan, world: World, out_dir: Path, rng: Random,
               filer) -> Path:
    folder = out_dir / "outlook_copy"
    folder.mkdir(parents=True, exist_ok=True)
    target = filer.file(folder, "Outlook.pst")
    if not FIXTURE.exists():
        raise FileNotFoundError(f"committed fixture missing: {FIXTURE}")
    shutil.copy2(FIXTURE, target)
    return target


WRITERS = {"copy": write_copy}


def write(plan: Plan, world: World, out_dir: Path, filer) -> list[Path]:
    rng = Random(f"{world.seed}:{plan.platform}")
    return [WRITERS[v](plan, world, out_dir, rng, filer) for v in config.VARIANTS[KIND]]
