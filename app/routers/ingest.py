"""Ingest: the drop zone, the report, and the prune gate.

Every route here is a WRITE tool, so every one needs the write toggle. The toggle
lives in the browser and is sent with each request — the server does not remember
it, because a remembered toggle is a toggle nobody remembers turning on.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from relate_comms import tools

router = APIRouter(prefix="/api", tags=["ingest"])


class IngestRequest(BaseModel):
    which: Literal["real", "sample"] = "real"
    paths: list[str] = Field(default_factory=list, description="Files to copy into the spool")
    email: list[str] = Field(default_factory=list, description="Mailboxes to read over IMAP")
    since: str | None = None
    until: str | None = None
    tz_offset_hours: float | None = Field(
        default=None,
        description="Hours the export's local times were written in. Omit to reuse the "
                    "offset this account was last parsed with.",
    )
    exclude_spam_groups: bool = Field(
        default=False,
        description="Facebook Messenger only: drop group threads that are mostly "
                    "link-spam and join-events.",
    )
    prune: bool = False
    write_enabled: bool = False


class PruneRequest(BaseModel):
    older_than_days: int = Field(default=3, ge=1, le=3650)
    write_enabled: bool = False
    confirm: bool = False


@router.post("/ingest")
def ingest(request: IngestRequest) -> dict:
    """Stage, parse, resolve, scrub, write, verify. Returns the full report."""
    return tools.ingest(
        which=request.which,
        paths_in=request.paths or None,
        email=request.email or None,
        since=request.since,
        until=request.until,
        tz_offset_hours=request.tz_offset_hours,
        exclude_spam_groups=request.exclude_spam_groups,
        prune=request.prune,
        write_enabled=request.write_enabled,
    )


@router.get("/ingest/verify")
def verify(which: Literal["real", "sample"] = "real") -> dict:
    """Re-parse the spool and report, per file, how many keys are missing."""
    return tools.verify_ingest(which)


@router.post("/ingest/prune")
def prune(request: PruneRequest) -> dict:
    """Delete verified spool files older than N days. Needs write **and** confirm."""
    return tools.prune_spool(
        older_than_days=request.older_than_days,
        write_enabled=request.write_enabled,
        confirm=request.confirm,
    )
