"""build / capture / clean. See `config` for every knob."""
from __future__ import annotations

import argparse
import shutil
import time
from random import Random
from typing import Callable

from . import config, plan as plan_module, world as world_module
from .writers import MODULES


def build(seed: int | None = None, platforms: list[str] | None = None,
          clean: bool = True, huge: bool = False,
          log: Callable[[str], None] | None = None) -> list[str]:
    """Generate every chosen platform into `out/<platform>/`.

    One output. There are no divisions: every mandated shape from `UNDESIRABLES.md` §12
    is present in every run, which is what a real export looks like.
    """
    say = log or (lambda _line: None)
    started = time.perf_counter()

    world = world_module.build(seed)
    say(f"world      seed={world.seed} people={len(world.people)} "
        f"cross-platform={world.multi_platform_share():.0%}")

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
        for path in module.write(plan_obj, world, out_dir):
            written.append(str(path))
            say(f"{'':<10} -> {path.relative_to(config.OUT_DIR)}")

    notes = plan_module.assert_contract(plans, huge=huge)
    for note in notes:
        say(f"{'':<10} - {note}")

    elapsed = time.perf_counter() - started
    say(f"done       {len(written)} files, "
        f"{plan_module.total_messages(plans)} messages, {elapsed:.2f}s -> {config.OUT_DIR}")
    return written


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
                        choices=["build", "clean", "capture", "knobs"])
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--platform", action="append", dest="platforms", default=None)
    parser.add_argument("--huge", action="store_true",
                        help="also emit the 1,600-message thread (UNDESIRABLES §9b)")
    parser.add_argument("--keep", action="store_true",
                        help="do not wipe out/<platform>/ before writing")
    parser.add_argument("--in", dest="in_dir", default=None)
    args = parser.parse_args(argv)

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
        build(args.seed, args.platforms, clean=not args.keep, huge=args.huge,
              log=print)
    except AssertionError as error:
        # A missing mandated shape is a generator bug, not a user error. Say what and
        # where, without a traceback.
        print("\nCONTRACT FAILED — the output would not exercise these app switches:")
        print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
