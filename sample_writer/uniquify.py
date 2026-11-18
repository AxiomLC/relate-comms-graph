"""Name disambiguation for `add` runs.

Writers emit files with fixed names many of them share (`result.json`,
`facebook-...zip`, `Outlook.pst`). In a plain build that is fine — `clean` wipes the
target first. But `add` writes *alongside* whatever is already in `out/` with no wipe,
so a second set must not clobber the first.

`Filer` hands a writer a resolved path before it writes: the name as asked, or
`name (1)`, `name (2)`, … Windows-style when the name is already taken on disk (or
claimed earlier in the same run). A whole-directory artifact gets the same treatment on
the directory, so a dragged-in `messenger_dir/` batch stays one coherent thing.
"""
from __future__ import annotations

from pathlib import Path


class Filer:
    """Resolves output names to paths that will not collide, per run."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._taken: set[str] = set()

    def _slot(self, candidate: Path) -> Path:
        if not self.enabled:
            return candidate
        key = str(candidate)
        if key not in self._taken and not candidate.exists():
            self._taken.add(key)
            return candidate
        # Windows dedupe: `base.png`, `base (1).png`, `base (2).png`…
        stem, suffix = candidate.stem, candidate.suffix
        n = 1
        while True:
            slot = candidate.with_name(f"{stem} ({n}){suffix}")
            slot_key = str(slot)
            if slot_key not in self._taken and not slot.exists():
                self._taken.add(slot_key)
                return slot
            n += 1

    def file(self, folder: Path, name: str) -> Path:
        """A file to be written *inside* an existing artifact folder."""
        return self._slot(folder / name)

    def dir(self, base: Path, name: str) -> Path:
        """A whole-directory artifact (e.g. `messenger_dir/`, `email_eml/`)."""
        return self._slot(base / name)