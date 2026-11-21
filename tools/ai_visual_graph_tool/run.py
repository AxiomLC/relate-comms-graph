#!/usr/bin/env python3
"""Entry point for the ai_visual_graph_tool — shells out to probe.js.

From the repo root:

    python tools/ai_visual_graph_tool/run.py                 # theme defaults, ring on
    python tools/ai_visual_graph_tool/run.py --no-ring       # the §6 experiment
    python tools/ai_visual_graph_tool/run.py --set physics.gravityCompound=5
    python tools/ai_visual_graph_tool/run.py --no-api        # reuse last_payload.json

Exit codes: 0 = measured, 1 = no payload, 2 = node missing, 3 = probe crashed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FALLBACK = HERE / "last_payload.json"


def _ensure_payload() -> None:
    """The probe fetches the payload itself via `python -c`; this pre-flight only
    fails fast with a readable message when the store cannot be read at all."""
    script = (
        "import json,sys;sys.path.insert(0,r'%s');"
        "from relate_comms import tools;"
        "p=tools.graph_slice(node_types=None,edge_types=None,limit=5,sort='messages');"
        "print(json.dumps({'nodes':p['counts']['nodes'],'total':p['total']}))"
        % str(ROOT)
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, cwd=str(ROOT)
    )
    if result.returncode != 0:
        print("ai_visual_graph_tool: cannot read the store via relate_comms.tools.",
              file=sys.stderr)
        print(result.stderr.strip(), file=sys.stderr)
        sys.exit(1)
    info = json.loads(result.stdout.strip().splitlines()[-1])
    if info.get("nodes", 0) == 0 and not FALLBACK.exists():
        print("ai_visual_graph_tool: store holds no drawable nodes; nothing to measure.",
              file=sys.stderr)
        sys.exit(1)


def main() -> None:
    if "--no-api" not in sys.argv:
        _ensure_payload()

    try:
        proc = subprocess.run(
            ["node", str(HERE / "probe.js"), *sys.argv[1:]],
            cwd=str(ROOT),
        )
    except FileNotFoundError:
        print("ai_visual_graph_tool: node not found on PATH.", file=sys.stderr)
        sys.exit(2)
    # Re-raise probe failures with their own output intact (already printed).
    if proc.returncode != 0:
        sys.exit(3)


if __name__ == "__main__":
    main()
