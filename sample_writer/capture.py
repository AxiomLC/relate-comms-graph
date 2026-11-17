"""capture — eval a real download and write the shape the writers are coded against.

Reads `in/` (or `--in <folder>`), runs each file through the app's own adapters, and
writes `schemas/<name>.json`. It never calls `ingest.run`, so `store/graph.rl` is not
touched, and it never writes to `in/`.

This is the honest definition of "same schema": whatever the adapter reports, including
`unknown_kinds`, `skipped` reasons and warnings, is what the writer must reproduce.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from . import config

SUFFIXES = {".zip", ".json", ".xml", ".pst", ".html", ".csv", ".txt"}


def _adapter_for(path: Path):
    from relate_comms import ingest
    from relate_comms.adapters import (
        linkedin, messenger, outlook_pst, sms, telegram, whatsapp,
    )

    platform = ingest.detect_platform(path)
    return {
        "telegram": telegram, "whatsapp": whatsapp, "messenger": messenger,
        "linkedin": linkedin, "sms": sms, "outlook": outlook_pst,
    }.get(platform or ""), platform


def _shape(result) -> dict:
    return {
        "platform": result.platform,
        "export_path": Path(str(result.export_path)).name,
        "counts": {
            "chats": len(result.chats),
            "messages": len(result.messages),
            "attachments": len(result.attachments),
        },
        "chat_fields": sorted({k for c in result.chats[:50] for k in vars(c)}),
        "message_fields": sorted({k for m in result.messages[:200] for k in vars(m)}),
        "kinds": dict(Counter(getattr(m, "kind", "text") for m in result.messages)),
        "unknown_kinds": result.unknown_kinds,
        "skipped": result.skipped,
        "warnings": result.warnings[:20],
        "groups": sum(1 for c in result.chats if getattr(c, "is_group", False)),
        "senders": len({getattr(m, "sender", None) for m in result.messages} - {None}),
    }


def capture_one(path: Path) -> dict | None:
    adapter, platform = _adapter_for(path)
    if adapter is None:
        return {"path": path.name, "recognised": False}
    try:
        result = adapter.parse(path)
    except Exception as error:                      # noqa: BLE001 - reported, not raised
        return {"path": path.name, "recognised": True, "platform": platform,
                "error": f"{type(error).__name__}: {error}"}
    return {"path": path.name, "recognised": True, **_shape(result)}


def run(in_dir: str | None = None) -> str:
    root = Path(in_dir) if in_dir else config.IN_DIR
    config.SCHEMA_DIR.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for item in sorted(root.rglob("*")):
        if not item.is_file() or item.suffix.lower() not in SUFFIXES:
            continue
        if item.name.startswith(".") or ".incoming" in item.parts:
            continue
        report = capture_one(item)
        if report is None:
            continue
        name = item.stem.replace(" ", "_")[:60]
        target = config.SCHEMA_DIR / f"{name}.json"
        target.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        lines.append(f"{item.name} -> {target.name}: {report}")
    return "\n".join(lines) or "nothing to capture"


if __name__ == "__main__":
    print(run(sys.argv[1] if len(sys.argv) > 1 else None))
