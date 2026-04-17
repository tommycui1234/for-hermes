#!/usr/bin/env python3
"""Restore Hermes core files from .bak backups created by install.py."""

from __future__ import annotations

import sys
from pathlib import Path


def find_hermes_agent_dir() -> Path:
    try:
        import hermes_cli
        base = Path(hermes_cli.__file__).resolve().parent.parent
        if (base / "run_agent.py").exists():
            return base
    except Exception:
        pass
    fallback = Path.home() / ".hermes" / "hermes-agent"
    if (fallback / "run_agent.py").exists():
        return fallback
    raise RuntimeError("Could not locate hermes-agent directory.")


def restore(path: Path) -> bool:
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        print(f"  ! No backup found for {path.name}, skipping")
        return False
    path.write_text(bak.read_text())
    print(f"  ✓ Restored {path.name}")
    return True


def main() -> int:
    print("🔧 Token Usage Monitoring Uninstaller")
    print("-" * 40)
    try:
        base = find_hermes_agent_dir()
    except RuntimeError as e:
        print(f"✗ {e}")
        return 1

    files = [
        base / "run_agent.py",
        base / "hermes_cli" / "config.py",
        base / "cli.py",
        base / "gateway" / "run.py",
        base / "gateway" / "display_config.py",
    ]
    restored = 0
    for path in files:
        if restore(path):
            restored += 1

    print("-" * 40)
    if restored:
        print(f"✅ Restored {restored} file(s). You may need to restart the gateway.")
    else:
        print("⚠ No backups were found to restore.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
