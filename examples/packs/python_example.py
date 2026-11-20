#!/usr/bin/env python3
"""Real Python workflow: venv, typed package, unittest suite and a CLI.

Run from the repository root::

    python3 examples/packs/python_example.py

The script builds a throw-away project in a temporary directory, creates a real
virtual environment without touching the network, writes a typed package with a
frozen dataclass, an async collector and a ``python -m`` entry point, then runs
compileall, the unittest suite, the CLI and the async path with the venv
interpreter. It prints PYTHON_PACK_OK only when every step passes.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "PYTHON_PACK_OK"
TEST_COUNT = 4

INIT = '''\
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Loan:
    member_id: int
    amount: int

    def __post_init__(self) -> None:
        if self.member_id <= 0:
            raise ValueError("member_id must be positive")
        if self.amount <= 0:
            raise ValueError("amount must be positive")


def parse_amount(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"not an integer: {raw!r}") from exc
    if value <= 0:
        raise ValueError("amount must be positive")
    return value


def summarize(amounts: Iterable[int]) -> dict[str, object]:
    values = list(amounts)
    return {"amounts": values, "count": len(values), "total": sum(values)}


async def collect(amounts: list[int]) -> int:
    queue: asyncio.Queue[int] = asyncio.Queue()
    for amount in amounts:
        queue.put_nowait(amount)
    total = 0
    while not queue.empty():
        total += await queue.get()
    return total
'''

MAIN = '''\
from __future__ import annotations

import argparse
import json

from . import parse_amount, summarize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loanlib")
    parser.add_argument("amounts", nargs="+", type=parse_amount)
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.amounts), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TESTS = '''\
from __future__ import annotations

import dataclasses
import unittest

from loanlib import Loan, parse_amount, summarize


class LoanTests(unittest.TestCase):
    def test_summarize(self) -> None:
        self.assertEqual(
            summarize([1250, 250]),
            {"amounts": [1250, 250], "count": 2, "total": 1500},
        )

    def test_rejects_zero_amount(self) -> None:
        with self.assertRaises(ValueError):
            Loan(member_id=7, amount=0)

    def test_parse_amount_rejects_text(self) -> None:
        with self.assertRaises(ValueError):
            parse_amount("twelve")

    def test_frozen_dataclass_blocks_mutation(self) -> None:
        loan = Loan(member_id=7, amount=1250)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            loan.amount = 1  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
'''

PYPROJECT = '''\
[project]
name = "loanlib"
version = "0.1.0"
description = "Small loan helpers used by the Python operations runbook"
requires-python = ">=3.10"
dependencies = []

[project.scripts]
loanlib = "loanlib.__main__:main"
'''

ASYNC_PROBE = (
    "import asyncio;"
    "from loanlib import collect;"
    "print(asyncio.run(collect([1250, 250])))"
)


def fail(message: str) -> int:
    print(f"PYTHON_PACK_FAIL: {message}")
    return 1


def run(label: str, command: list[str], cwd: Path, timeout: int = 120) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(fail(f"{label} timed out after {timeout}s"))
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()[-1600:]
        raise SystemExit(fail(f"{label} exited {result.returncode}: {detail}"))
    # unittest writes its report to stderr; the caller needs both streams.
    return result.stdout + result.stderr


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="zc-python-") as tmp:
        root = Path(tmp)
        package = root / "loanlib"
        tests = root / "tests"
        package.mkdir()
        tests.mkdir()
        (package / "__init__.py").write_text(INIT, encoding="utf-8")
        (package / "__main__.py").write_text(MAIN, encoding="utf-8")
        (tests / "test_loanlib.py").write_text(TESTS, encoding="utf-8")
        (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")

        run("venv", [sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")], root)
        python = root / ".venv" / "bin" / "python"
        if not python.is_file():
            return fail(f"venv python is missing at {python}")

        version = run("venv python -V", [str(python), "-V"], root).strip()
        if not version.startswith("Python 3."):
            return fail(f"unexpected venv interpreter: {version!r}")

        prefixes = run(
            "venv isolation",
            [str(python), "-c", "import sys; print(sys.prefix); print(sys.base_prefix)"],
            root,
        ).splitlines()
        if len(prefixes) != 2 or prefixes[0] == prefixes[1]:
            return fail(f"venv is not isolated: {prefixes}")

        run("compileall", [str(python), "-m", "compileall", "-q", "loanlib", "tests"], root)

        test_output = run(
            "unittest",
            [str(python), "-m", "unittest", "discover", "-s", "tests", "-v"],
            root,
        )
        if f"Ran {TEST_COUNT} tests" not in test_output:
            return fail(f"unittest ran an unexpected number of tests: {test_output.strip()[-600:]}")
        if "\nOK" not in test_output and not test_output.rstrip().endswith("OK"):
            return fail(f"unittest did not report OK: {test_output.strip()[-600:]}")

        cli_output = run("python -m loanlib", [str(python), "-m", "loanlib", "1250", "250"], root)
        try:
            payload = json.loads(cli_output)
        except json.JSONDecodeError as exc:
            return fail(f"CLI did not print JSON: {exc}: {cli_output!r}")
        expected = {"amounts": [1250, 250], "count": 2, "total": 1500}
        if payload != expected:
            return fail(f"CLI payload is {payload!r}, expected {expected!r}")

        async_output = run("asyncio", [str(python), "-c", ASYNC_PROBE], root).strip()
        if async_output != "1500":
            return fail(f"async collect returned {async_output!r}, expected '1500'")

        print(f"venv={version} isolated=true tests={TEST_COUNT} unittest=OK")
        print(f"cli={json.dumps(payload, sort_keys=True)} async_total={async_output}")
        print(MARKER)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
