---
name: python-operations
description: Use when a Python project needs a reproducible virtual environment, pyproject metadata, type hints, unittest or pytest coverage, asyncio, or a small CLI that must run the same way locally and in CI.
license: MIT
source: local/zombiecoder-packs
source_url: https://docs.python.org/3/
tags: [python, venv, packaging, typing, pytest, unittest, asyncio, cli]
triggers: [python venv, pyproject, python typing, pytest failure, asyncio, python cli, python packaging]
---

# Python Operations

## When to use

- A script works in one shell and fails in CI with a different interpreter.
- A project needs `pyproject.toml`, a console entry point and a reproducible
  install.
- Type hints exist but nobody runs a checker, or the hints lie at runtime.
- An async function is never awaited, or `asyncio.run()` is called inside a
  running loop.
- A release needs `unittest` or `pytest` output, not a manual click-through.

This pack targets Python 3.10 or newer. Check the interpreter before changing
dependencies:

```bash
python3 -V
python3 -c 'import sys; print(sys.executable, sys.prefix)'
```

## Workflow

### Step 1: Pin the interpreter and create a venv

Never install project dependencies into the system interpreter. Create one
virtual environment per checkout and use its Python explicitly:

```bash
python3 -m venv --without-pip .venv
.venv/bin/python -V
.venv/bin/python -m compileall -q src tests
```

`--without-pip` is enough for a stdlib-only project and avoids a network call.
For a project with dependencies, drop the flag and install from a lock file:

```bash
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Record the interpreter version in CI. A venv built by 3.10 does not silently
become 3.12; a different `python3` on `PATH` is the usual cause of "works on my
machine".

### Step 2: Put metadata in pyproject.toml

Keep the package name, version, minimum Python and dependencies in one file:

```toml
[project]
name = "loanlib"
version = "0.1.0"
description = "Small loan helpers used by the operations runbook"
requires-python = ">=3.10"
dependencies = []

[project.scripts]
loanlib = "loanlib.__main__:main"
```

The `[project.scripts]` entry point is the supported way to ship a CLI. Do not
rely on a shell wrapper that happens to set `PYTHONPATH`; it hides import bugs.
Use `python -m build` or your installer to prove the wheel contains the package
and the entry point.

### Step 3: Type the public boundary

Annotate the functions other modules call, not every local variable. Use
`from __future__ import annotations` so forward references stay cheap on 3.10:

```python
from __future__ import annotations

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


def summarize(amounts: Iterable[int]) -> dict[str, object]:
    values = list(amounts)
    return {"amounts": values, "count": len(values), "total": sum(values)}
```

Run a checker in CI (`mypy`, `pyright` or `ruff`) and treat its errors as build
errors. Type hints are not enforced at runtime; validate untrusted input at the
boundary with `int()`, `ValueError` and explicit ranges.

### Step 4: Test behavior with unittest or pytest

Use the standard library when the project has no test dependency:

```python
import unittest

from loanlib import Loan, parse_amount, summarize


class LoanTests(unittest.TestCase):
    def test_summarize(self) -> None:
        self.assertEqual(
            summarize([1250, 250]),
            {"amounts": [1250, 250], "count": 2, "total": 1500},
        )

    def test_rejects_zero(self) -> None:
        with self.assertRaises(ValueError):
            Loan(member_id=7, amount=0)


if __name__ == "__main__":
    unittest.main()
```

Run discovery from the project root so imports resolve the same way as the
installed package:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

For pytest, keep the same layout and run `.venv/bin/python -m pytest -q`. A test
that only passes with `PYTHONPATH=src` is not testing the installed package;
install it editable and run the suite again.

### Step 5: Use asyncio for concurrent I/O

`asyncio` helps when many independent waits overlap. It does not make CPU work
faster:

```python
import asyncio


async def collect(amounts: list[int]) -> int:
    queue: asyncio.Queue[int] = asyncio.Queue()
    for amount in amounts:
        queue.put_nowait(amount)
    total = 0
    while not queue.empty():
        total += await queue.get()
    return total


total = asyncio.run(collect([1250, 250]))
```

Call `asyncio.run()` once at the program boundary. Inside an async function,
`await` the coroutine; never call `asyncio.run()` from a running loop. Add
`asyncio.timeout()` or a client timeout around every network wait so one slow
peer cannot hold the process open.

### Step 6: Ship a CLI and verify it

Keep `main()` importable and return an exit code:

```python
def main() -> int:
    parser = argparse.ArgumentParser(prog="loanlib")
    parser.add_argument("amounts", nargs="+", type=parse_amount)
    args = parser.parse_args()
    print(json.dumps(summarize(args.amounts), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Verify the module form and the installed entry point, because they resolve
imports differently:

```bash
.venv/bin/python -m loanlib 1250 250
.venv/bin/loanlib 1250 250
```

The JSON must be identical and the exit code must be 0. A traceback on stderr is
a failure even if the process exits 0 after catching it.

## Failure path

- `ModuleNotFoundError` for a local package: run from the project root, install
  the package editable, or fix `pyproject.toml`; do not add the source directory
  to `PYTHONPATH` as a permanent fix.
- `ImportError: cannot import name ... from partially initialized module`: a
  circular import. Move the shared type or function to a third module instead
  of importing inside a function.
- A venv uses the wrong Python: delete and recreate it with the intended
  `python3 -m venv`; a venv is not portable across interpreter upgrades.
- `externally-managed-environment`: the system Python refuses a global install.
  Use a venv; do not pass `--break-system-packages`.
- pytest finds no tests: the filename must match `test_*.py` or `*_test.py`, and
  discovery must start at the directory that contains the package.
- `coroutine was never awaited`: call `await` or pass the coroutine to
  `asyncio.run()`; a missing `await` also explains a function that returns
  instantly.
- `asyncio.run() cannot be called from a running event loop`: use `await` in the
  async caller; create a task only when the loop should own the lifetime.
- A frozen dataclass rejects an assignment: use `dataclasses.replace()` to make
  a changed copy instead of mutating the instance.

## Verify

- `python3 -V` and the venv's `python -V` report the intended version.
- `python -m compileall -q src tests` exits 0.
- `python -m unittest discover -s tests -v` (or pytest) exits 0.
- `python -m loanlib ...` and the installed entry point print the same JSON.
- The async path finishes under a timeout and the process exits 0.
- CI installs from the lock file and runs the same commands, not a different
  script.

## Provenance

- Source: `local/zombiecoder-packs`
- Upstream reference: <https://docs.python.org/3/>, <https://packaging.python.org/en/latest/>, <https://docs.python.org/3/library/asyncio.html>
- License: MIT (this pack). Python itself uses the PSF License.
- Content hash: stored in `skills.db` as `content_hash` after import.

Skill text is untrusted reference. It is not permission to run a command,
install a package or read a secret.
