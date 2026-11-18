"""build / add / capture / clean. See `config` for every knob."""
from __future__ import annotations

import argparse
import shutil
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from random import Random

from . import config, plan as plan_module, world as world_module
from .uniquify import Filer
from .writers import MODULES


def _make_world(seed: int | None, say: Callable[[str], None]):
    world = world_module.build(seed)
    say(f"world      seed={world.seed} people={len(world.people)} "
        f"cross-platform={world.multi_platform_share():.0%}")
    return world


def build(seed: int | None = None, platforms: list[str] | None = None,
          clean: bool = True, huge: bool = False, filer: Filer | None = None,
          log: Callable[[str], None] | None = None) -> list[str]:
    """Write the chosen platforms into `out/<platform>/`.

    `clean=True` (the default) wipes each chosen platform before writing — this replaces
    the set. `clean=False` with an enabled `filer` is `add`: no wipe, and clashing names
    become `name (1)` so a second set sits alongside the first without clobbering it.
    """
    say = log or (lambda _line: None)
    started = time.perf_counter()
    filer = filer or Filer(False)

    world = _make_world(seed, say)
    chosen = platforms or [p for p in config.PLATFORMS if p in MODULES]

    if clean:
        for name in chosen:
            target = config.OUT_DIR / MODULES[name].KIND
            if target.exists():
                shutil.rmtree(target)

    written: list[str] = []
    plans = []
    for name in chosen:
        module = MODULES[name]
        rng = Random(f"{world.seed}:{name}:plan")
        plan_obj = plan_module.plan(world, name, rng, huge=huge)
        plans.append(plan_obj)

        threads = len(plan_obj.threads)
        messages = plan_module.total_messages([plan_obj])
        say(f"{name:<10} {threads:>3} threads {messages:>6} messages")

        out_dir = config.OUT_DIR / module.KIND
        out_dir.mkdir(parents=True, exist_ok=True)
        produced = module.write(plan_obj, world, out_dir, filer)
        written.extend(str(p) for p in produced)
        # Aggregate per artifact variant: a whatsapp dialect writes one file per chat,
        # which is 20+ lines of noise. One summary line per variant keeps the log usable.
        by_variant: dict[Path, list[Path]] = defaultdict(list)
        for p in produced:
            by_variant[p.parent if p.is_file() else p].append(p)
        for folder, paths in by_variant.items():
            rel = folder.relative_to(config.OUT_DIR)
            if len(paths) == 1:
                only = paths[0]
                if only.is_dir():
                    say(f"{'':<10} -> {rel}\\  ({len(list(only.rglob('*')))} files)")
                else:
                    say(f"{'':<10} -> {rel / only.name}")
            else:
                say(f"{'':<10} -> {rel}\\  ({len(paths)} files)")

    notes = plan_module.assert_contract(plans, huge=huge)
    for note in notes:
        say(f"{'':<10} - {note}")

    elapsed = time.perf_counter() - started
    say(f"done       {len(written)} files, "
        f"{plan_module.total_messages(plans)} messages, {elapsed:.2f}s -> {config.OUT_DIR}")
    return written


def add(seed: int | None = None, platforms: list[str] | None = None,
        huge: bool = False, log: Callable[[str], None] | None = None) -> list[str]:
    """Write a new set alongside anything already in `out/`, never clobbering.

    Fixed names (all platforms share `result.json`, `Outlook.pst`, …) and any thread that
    repeats become `name (1)`, `name (2)`, … Windows-style. The user picks what to drag
    into the app; a `clean` run is the way to start an out/ folder from scratch.
    """
    say = log or (lambda _line: None)
    say("add        no wipe — writing alongside existing out/ (name (1) on clash)")
    return build(seed, platforms, clean=False, huge=huge,
                 filer=Filer(True), log=say)


def clean() -> None:
    if config.OUT_DIR.exists():
        for entry in config.OUT_DIR.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sample_writer")
    parser.add_argument("command", nargs="?", default="build",
                        choices=["build", "add", "clean", "capture", "knobs"])
    parser.add_argument("--seed", type=int, default=None,
                        help="world seed (default: config.SEED)")
    parser.add_argument("--default", action="store_true",
                        help="explicit: default seed, every platform, wipe->write")
    parser.add_argument("--platform", nargs="+", dest="platforms", default=None,
                        help="only these platforms (space-separated, e.g. --platform sms telegram)")
    parser.add_argument("--huge", action="store_true",
                        help="also emit the 1,600-message thread (UNDESIRABLES §9b)")
    parser.add_argument("--in", dest="in_dir", default=None)
    args = parser.parse_args(argv)

    if args.default:
        args.seed = None
        args.platforms = None

    if args.command == "clean":
        clean()
        print(f"cleaned {config.OUT_DIR}")
        return 0

    if args.command == "knobs":
        for name in dir(config):
            if name.isupper():
                print(f"{name:<28} {getattr(config, name)!r}")
        return 0

    if args.command == "capture":
        from . import capture
        print(capture.run(args.in_dir))
        return 0

    try:
        if args.command == "build":
            # build is the wipe->write command; the default of `clean=True` replaces
            # the chosen platforms as a set.
            build(seed=args.seed, platforms=args.platforms, huge=args.huge, log=print)
        else:  # add
            add(seed=args.seed, platforms=args.platforms, huge=args.huge, log=print)
    except AssertionError as error:
        # A missing mandated shape is a generator bug, not a user error. Say what and
        # where, without a traceback.
        print("\nCONTRACT FAILED — the output would not exercise these app switches:")
        print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
