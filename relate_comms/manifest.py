"""What has already been ingested, so a second run can say so instead of re-parsing.

**This is a shortcut, not the authority.** `writer.verify_present()` re-reads the store
and compares key sets; that is what decides whether a spool file may be pruned. The
manifest only answers "have I seen this exact file before?", which is cheap and is the
question the UI asks before starting a long parse.

WHY A SAMPLED FINGERPRINT
-------------------------
The real SMS export is 825 MB. A full SHA-256 is exact but costs a full read of the
file — the very cost the manifest exists to avoid. So the fingerprint is the file size
plus SHA-256 of the first and last 256 KB.

That is safe for this job because the files are exports, not arbitrary data: two
exports of the same account differ in the middle (new messages) *and* in size. A file
that matched on size, head and tail but differed only in the middle would have to be a
deliberate edit, which is not a case this app is defending against. If that ever
matters, `fingerprint(full=True)` is the exact path.

WHY IT LIVES IN `store/profile/`
--------------------------------
Same reason `identity.json` does: it is a fact about *this account's* data, it must
survive a restart, and it must never be committed. `store/` is gitignored.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_FILE = "ingested.json"

# How much of each end is hashed. 256 KB is far more than any export header needs and
# still reads in milliseconds.
SAMPLE_BYTES = 256 * 1024


def fingerprint(path: str | Path, *, full: bool = False) -> str:
    """A stable id for one file's contents.

    `full=True` hashes the whole file — exact, and slow on a large export. The default
    samples both ends, which is what the preview uses.
    """
    target = Path(path)
    size = target.stat().st_size
    digest = hashlib.sha256()
    digest.update(str(size).encode("ascii"))

    if full:
        with target.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    with target.open("rb") as handle:
        digest.update(handle.read(SAMPLE_BYTES))
        if size > SAMPLE_BYTES * 2:
            handle.seek(-SAMPLE_BYTES, 2)
            digest.update(handle.read(SAMPLE_BYTES))
    return digest.hexdigest()


def _path(profile_dir: str | Path) -> Path:
    return Path(profile_dir) / MANIFEST_FILE


def load(profile_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Every recorded file, keyed by fingerprint. A missing or broken file is empty."""
    target = _path(profile_dir)
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    files = data.get("files")
    return files if isinstance(files, dict) else {}


def lookup(profile_dir: str | Path, digest: str) -> dict[str, Any] | None:
    return load(profile_dir).get(digest)


def record(
    profile_dir: str | Path,
    digest: str,
    *,
    platform: str,
    path: str,
    messages: int,
    threads: int,
    bytes_: int,
) -> None:
    """Remember one successfully verified file.

    Called only after `verify_present()` said yes. A file that failed to land must not
    be recorded, or the next run would skip a parse that never actually wrote anything.
    """
    target = _path(profile_dir)
    target.parent.mkdir(parents=True, exist_ok=True)

    files = load(profile_dir)
    files[digest] = {
        "platform": platform,
        "path": path,
        "messages": messages,
        "threads": threads,
        "bytes": bytes_,
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    target.write_text(json.dumps({"files": files}, indent=2), encoding="utf-8")


def forget(profile_dir: str | Path, digest: str) -> bool:
    """Drop one entry. Used when a file is pruned, so the manifest cannot outlive it."""
    files = load(profile_dir)
    if digest not in files:
        return False
    files.pop(digest)
    _path(profile_dir).write_text(json.dumps({"files": files}, indent=2), encoding="utf-8")
    return True
