#!/usr/bin/env python3
"""One-command installer for the ZombieCoder skill packs.

Run it from any directory inside the project you want to configure. It finds
the project root, detects the operating system and the installed editors, and
installs the eight packs into the detected clients' skill paths.

Usage::

    python3 install.py
    python3 install.py --detect
    python3 install.py --detect --json
    python3 install.py --scope global
    python3 install.py --check
    python3 install.py --client all --target /path/to/project

Without ``--client`` or ``--detect`` the script defaults to ``--auto``.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))

from install_client_skills import main  # noqa: E402


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if not any(
        argument in ("--auto", "--client", "--detect", "--help", "-h")
        for argument in arguments
    ):
        arguments = ["--auto", *arguments]
    sys.argv = [sys.argv[0], *arguments]
    raise SystemExit(main())
