"""Ingest: the drop zone, the report, and the prune gate.

Every route here is a WRITE tool, so every one needs the write toggle. The toggle
lives in the browser and is sent with each request — the server does not remember
it, because a remembered toggle is a toggle nobody remembers turning on.

Two routes are not store writes and say so: `POST /api/ingest/upload` copies a file
into the spool (the same custody point `stage()` uses), and `POST /api/ingest/env`
writes IMAP credentials to `./.env`. Both still require the toggle, because both
touch the user's disk.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field

from relate_comms import paths, tools

router = APIRouter(prefix="/api", tags=["ingest"])

# The three platforms that have groups, so the three that can carry a silent-group
# gate. Mirrors `ingest._SILENT_GROUP_PLATFORMS`; kept here so the router can validate
# a request without importing the pipeline.
SILENT_GROUP_PLATFORMS = ("telegram", "whatsapp", "messenger")

# The two platforms the long-silent-thread spam rule applies to.
SPAM_THREAD_PLATFORMS = ("email", "outlook")

# Upload cap. A Telegram bulk export is a folder, not a file, so the picker is for the
# single-file platforms; 2 GB covers the 825 MB SMS XML with room to spare.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024


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
    exclude_silent_groups: bool = Field(
        default=True,
        description="Telegram / WhatsApp / Messenger: drop group threads the owner never "
                    "spoke in",
    )
    silent_group_platforms: list[str] | None = Field(
        default=None,
        description="Which of the three group platforms the silent-group gate applies to. "
                    "None means all three.",
    )
    exclude_spam_threads: bool = Field(
        default=True,
        description="Email / Outlook: drop threads of 10+ messages the owner never replied to",
    )
    spam_thread_platforms: list[str] | None = Field(
        default=None,
        description="Which of Email / Outlook the spam-thread rule applies to. None means both.",
    )
    exclude_spam_groups: bool = Field(
        default=False,
        description="Facebook Messenger only: drop group threads that are mostly "
                    "link-spam and join-events.",
    )
    prune: bool = False
    prune_keep: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Prune policy: None = older than 3 days, 0 = keep nothing, "
                    "1 = keep the newest ingest's files, 2 = keep the newest two.",
    )
    write_enabled: bool = False
    delta: bool = Field(
        default=True,
        description="Skip messages the store already holds for that platform, before "
                    "the write and before extraction. Turn off to re-process every "
                    "message — required after an extractor change, or to re-derive "
                    "Places for rows written before extraction existed.",
    )


class PruneRequest(BaseModel):
    older_than_days: int = Field(default=3, ge=1, le=3650)
    write_enabled: bool = False
    confirm: bool = False


class EnvRequest(BaseModel):
    """IMAP credentials, written to `./.env`.

    The password is written and never read back. `GET /api/ingest/env` reports only
    whether a key is present, never its value.
    """

    email: str = Field(description="Mailbox address, e.g. dev@w57th.agency")
    password: str = Field(description="Password or app password. Never echoed back.")
    host: str | None = Field(default=None, description="IMAP host. Omit to derive from the domain.")
    port: int = Field(default=993, ge=1, le=65535)
    write_enabled: bool = False


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
        exclude_silent_groups=request.exclude_silent_groups,
        silent_group_platforms=request.silent_group_platforms,
        exclude_spam_threads=request.exclude_spam_threads,
        spam_thread_platforms=request.spam_thread_platforms,
        prune=request.prune,
        prune_keep=request.prune_keep,
        write_enabled=request.write_enabled,
        delta=request.delta,
    )


@router.post("/ingest/upload")
async def upload(
    files: list[UploadFile] = File(...),
    write_enabled: bool = False,
) -> dict:
    """Copy uploaded files into the spool, one or many.

    The browser can hand over file *contents* but never a filesystem path, so this is
    the only way a drop box can work. Files land in `spool/real/<platform>/`, chosen by
    content — the same rule `stage()` applies to a pasted path, so a dropped file and a
    pasted path end up in the same place.

    A file whose shape is not recognised is filed under `unrecognised/` and reported,
    never guessed at and never deleted.
    """
    from relate_comms import ingest as ingest_module

    tools.require(tools.Access.WRITE, write_enabled=write_enabled)

    staged: list[dict] = []
    for upload_file in files:
        # A folder pick sends `relativePath`-style names (`ChatExport/result.json`).
        # Keep the parent folder, because Telegram's exporter writes a directory and
        # two exports of one account share the filename `result.json`.
        raw_name = (upload_file.filename or "upload").replace("\\", "/")
        parts = [p for p in raw_name.split("/") if p not in ("", ".", "..")]
        if not parts:
            continue
        name = parts[-1]
        parent = parts[-2] if len(parts) > 1 else ""
        # A temp copy first: detection reads the content, and the spool must only ever
        # hold files that were fully written.
        temp = paths.spool_dir() / ".incoming" / name
        temp.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with temp.open("wb") as handle:
            while chunk := await upload_file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    handle.close()
                    temp.unlink(missing_ok=True)
                    raise tools.ToolError(
                        f"{name} is larger than the {MAX_UPLOAD_BYTES // (1024 ** 3)} GB "
                        "upload limit; copy it into spool/real/ yourself and paste the path"
                    )
                handle.write(chunk)

        platform = ingest_module.detect_platform(temp) or "unrecognised"
        target_dir = paths.real_dir() / platform / parent / name
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp, target_dir)
        staged.append({
            "name": f"{parent}/{name}" if parent else name,
            "path": str(target_dir),
            "platform": platform,
            "bytes": written,
            "recognised": platform != "unrecognised",
        })

    return {"staged": staged, "ok": all(item["recognised"] for item in staged)}


@router.get("/ingest/env")
def env_status() -> dict:
    """Which `.env` keys exist. Never returns a value.

    The modal needs this to say "credentials present" without ever holding the
    password. A missing key is reported by name, never by value.
    """
    from relate_comms.adapters import email_imap

    present = {}
    for name, (_host, user_var, pass_var, _port) in email_imap.ENV_ACCOUNTS.items():
        env = email_imap._dotenv()
        present[name] = {
            "email_key": user_var,
            "password_key": pass_var,
            "email_present": bool(env.get(user_var) or os.environ.get(user_var)),
            "password_present": bool(env.get(pass_var) or os.environ.get(pass_var)),
        }
    custom = email_imap._dotenv()
    present["custom"] = {
        "email_key": "CUSTOM_EMAIL",
        "password_key": "CUSTOM_PASSWORD",
        "email_present": bool(custom.get("CUSTOM_EMAIL")),
        "password_present": bool(custom.get("CUSTOM_PASSWORD")),
    }
    return {"providers": present}


@router.post("/ingest/env")
def save_env(request: EnvRequest) -> dict:
    """Write IMAP credentials to `./.env`, replacing only the keys involved.

    Appends or replaces, never rewrites the file — a user's other keys must survive.
    The password is written and never returned, logged or echoed.
    """
    tools.require(tools.Access.WRITE, write_enabled=request.write_enabled)

    from relate_comms.adapters import email_imap

    domain = request.email.rsplit("@", 1)[-1].lower() if "@" in request.email else ""
    host = request.host or _host_for_domain(domain)
    if not host:
        raise tools.ToolError(
            f"no known IMAP host for {domain or 'that address'}; "
            "enter the host explicitly (e.g. mail.yourdomain.com)"
        )

    key = _provider_key(domain)
    user_var, pass_var = _env_names(key)

    updates = {
        user_var: request.email.strip(),
        pass_var: request.password,
        f"{key.upper()}_HOST": host,
        f"{key.upper()}_PORT": str(request.port),
    }
    _write_dotenv(updates)

    return {
        "saved": sorted(updates),
        "provider": key,
        "host": host,
        "port": request.port,
        # Deliberately no password, no length, no prefix.
    }


class TruncateRequest(BaseModel):
    """Wipe the graph. Needs write **and** confirm, like every destructive tool."""

    write_enabled: bool = False
    confirm: bool = False
    also_identity: bool = Field(
        default=False,
        description="Also drop the per-platform owners and tz offsets. Use when "
                    "switching accounts, not when re-ingesting the same one.",
    )
    also_spool: bool = Field(
        default=False,
        description="Also delete the exports in spool/real/. Off by default — those "
                    "are the user's own downloads.",
    )


@router.post("/ingest/truncate")
def truncate(request: TruncateRequest) -> dict:
    """Delete the graph and the dedup manifest. Destructive; needs confirm."""
    return tools.truncate_store(
        write_enabled=request.write_enabled,
        confirm=request.confirm,
        also_identity=request.also_identity,
        also_spool=request.also_spool,
    )


@router.get("/ingest/preview")
def preview(which: Literal["real", "sample"] = "real") -> dict:
    """What is in the spool, and what has already been ingested. Read-only.

    Reports size and duplicate status per file. Deliberately does not count messages:
    that needs the full parse this exists to avoid.
    """
    return tools.preview_ingest(which)


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


# ------------------------------------------------------------------ .env helpers

def _host_for_domain(domain: str) -> str | None:
    """The IMAP host for a mail domain, from the adapter's own table.

    Detection, not a selector: the user types an address and the host follows. The
    field stays editable, so an unknown domain is a prompt, not a refusal.
    """
    from relate_comms.adapters import email_imap

    for _name, (host, _u, _p, _port) in email_imap.ENV_ACCOUNTS.items():
        if "{domain}" in host:
            continue
        if host.split(".")[-2:] and domain and domain.split(".")[0] in host:
            return host
    known = {
        "gmail.com": "imap.gmail.com",
        "googlemail.com": "imap.gmail.com",
        "outlook.com": "outlook.office365.com",
        "hotmail.com": "outlook.office365.com",
        "live.com": "outlook.office365.com",
        "yahoo.com": "imap.mail.yahoo.com",
        "icloud.com": "imap.mail.me.com",
        "me.com": "imap.mail.me.com",
        "zoho.com": "imap.zoho.com",
        "fastmail.com": "imap.fastmail.com",
        "gmx.com": "imap.gmx.com",
        "gmx.net": "imap.gmx.com",
        "yandex.com": "imap.yandex.com",
        "aol.com": "imap.aol.com",
        "hostinger.com": "imap.hostinger.com",
    }
    if domain in known:
        return known[domain]
    # cPanel / generic hosting: the mail host is the domain itself.
    return f"mail.{domain}" if domain else None


def _provider_key(domain: str) -> str:
    """The `.env` key prefix for a domain. `custom` for anything unlisted."""
    from relate_comms.adapters import email_imap

    for name, (host, _u, _p, _port) in email_imap.ENV_ACCOUNTS.items():
        if "{domain}" in host:
            continue
        if domain and domain.split(".")[0] in host:
            return name
    return "custom"


def _env_names(key: str) -> tuple[str, str]:
    from relate_comms.adapters import email_imap

    if key in email_imap.ENV_ACCOUNTS:
        _host, user_var, pass_var, _port = email_imap.ENV_ACCOUNTS[key]
        return user_var, pass_var
    return "CUSTOM_EMAIL", "CUSTOM_PASSWORD"


def _write_dotenv(updates: dict[str, str]) -> None:
    """Replace or append the given keys, leaving every other line untouched."""
    path = paths.data_root() / ".env"
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)

    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")

    path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
