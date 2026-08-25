"""One-shot migration from the retired singleton store to an explicit tenant."""

from __future__ import annotations

import os
from pathlib import Path

from tenant_context import normalize_identity


def migrate_singleton_store(root: Path, identity: str | None) -> bool:
    """Move legacy files at ``root`` into one explicit tenant; never merge."""
    root.mkdir(parents=True, exist_ok=True)
    legacy_entries = [entry for entry in root.iterdir() if entry.name != "tenants"]
    if not legacy_entries:
        return False
    if not identity:
        raise RuntimeError("WHATSAPP_MIGRATION_TENANT_ID is required for the existing singleton store")

    canonical = normalize_identity(identity)
    target = root / "tenants" / canonical / "store"
    if target.exists():
        raise RuntimeError(f"refusing to merge singleton store into existing tenant {canonical}")
    staging = target.with_name(".store-migrating")
    if staging.exists():
        raise RuntimeError(f"incomplete prior migration exists for tenant {canonical}")
    staging.mkdir(parents=True)
    moved: list[Path] = []
    try:
        for source in legacy_entries:
            destination = staging / source.name
            source.rename(destination)
            moved.append(destination)
        staging.rename(target)
        (target / ".bridge-token").unlink(missing_ok=True)
    except OSError:
        for destination in reversed(moved):
            destination.rename(root / destination.name)
        if staging.exists():
            staging.rmdir()
        raise
    return True


def migrate_from_environment(root: Path) -> bool:
    return migrate_singleton_store(root, os.getenv("WHATSAPP_MIGRATION_TENANT_ID"))
