#!/usr/bin/env python3
"""Real Apache hosting check: document root, permissions, dotfile deny, headers.

Run from the repository root:

    python3 examples/packs/apache_example.py

The script writes a temporary document root and a minimal Apache 2.4 config,
runs ``apache2 -t``, starts the server on a free loopback port, requests the
index and a dotfile, checks the security header, and stops the server. It
prints APACHE_PACK_OK only when every assertion passes.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

APACHE = shutil.which("apache2")
MODULES = Path("/usr/lib/apache2/modules")


def fail(message: str, log: Path | None = None) -> int:
    print(f"APACHE_PACK_FAIL: {message}")
    if log is not None and log.is_file():
        print("--- apache error log tail ---")
        print(log.read_text(encoding="utf-8", errors="replace")[-1600:].strip())
    return 1


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(url: str) -> tuple[int, dict[str, str], str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, dict(response.headers), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode("utf-8", "replace")


def main() -> int:
    if not APACHE:
        return fail("apache2 is not on PATH")
    required = (
        "mod_mpm_event.so",
        "mod_authz_core.so",
        "mod_dir.so",
        "mod_mime.so",
        "mod_headers.so",
    )
    missing = [name for name in required if not (MODULES / name).is_file()]
    if missing:
        return fail(f"missing Apache modules: {missing}")

    with tempfile.TemporaryDirectory(prefix="zc-apache-") as tmp_name:
        tmp = Path(tmp_name)
        public = tmp / "public"
        logs = tmp / "logs"
        public.mkdir()
        logs.mkdir()

        index = public / "index.html"
        index.write_text(
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<title>ZC hosting check</title></head>"
            "<body><h1>ZC_HOSTING_OK</h1></body></html>\n",
            encoding="utf-8",
        )
        (public / ".env").write_text(
            "ZC_TEST_SECRET=not-a-real-secret\n", encoding="utf-8"
        )
        (public / "uploads").mkdir()
        (public / "uploads" / "note.txt").write_text("not public\n", encoding="utf-8")
        (tmp / "shared").mkdir()
        (tmp / "shared" / ".env").write_text(
            "APP_KEY=test-only\n", encoding="utf-8"
        )

        os.chmod(public, 0o755)
        os.chmod(index, 0o644)
        os.chmod(public / ".env", 0o640)
        os.chmod(tmp / "shared", 0o750)
        os.chmod(tmp / "shared" / ".env", 0o600)

        for path in (public, index, public / ".env", tmp / "shared", tmp / "shared" / ".env"):
            if path.stat().st_mode & 0o002:
                return fail(f"world-writable fixture: {path}")

        port = free_port()
        config = tmp / "httpd.conf"
        error_log = logs / "error.log"
        config.write_text(
            f"""ServerRoot "/etc/apache2"
Listen 127.0.0.1:{port}
ServerName 127.0.0.1
PidFile "{tmp / 'apache.pid'}"
ErrorLog "{error_log}"
LogLevel warn

LoadModule mpm_event_module {MODULES / 'mod_mpm_event.so'}
LoadModule authz_core_module {MODULES / 'mod_authz_core.so'}
LoadModule dir_module {MODULES / 'mod_dir.so'}
LoadModule mime_module {MODULES / 'mod_mime.so'}
LoadModule headers_module {MODULES / 'mod_headers.so'}

DocumentRoot "{public}"
<Directory "{public}">
    Options -Indexes +FollowSymLinks
    AllowOverride None
    Require all granted
    <FilesMatch "^\\.">
        Require all denied
    </FilesMatch>
</Directory>
DirectoryIndex index.html
TypesConfig /etc/mime.types
AddType text/html .html
Header always set X-Content-Type-Options "nosniff"
""",
            encoding="utf-8",
        )

        tested = subprocess.run(
            [APACHE, "-t", "-f", str(config)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if tested.returncode != 0:
            return fail(f"apache2 -t failed: {tested.stderr.strip()}", error_log)

        proc = subprocess.Popen(
            [APACHE, "-f", str(config), "-DFOREGROUND"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = time.time() + 15
            status = 0
            body = ""
            headers: dict[str, str] = {}
            while time.time() < deadline:
                if proc.poll() is not None:
                    return fail(f"apache2 exited with {proc.returncode}", error_log)
                try:
                    status, headers, body = request(base + "/")
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.15)
            if status != 200 or "ZC_HOSTING_OK" not in body:
                return fail(f"index returned {status}, body={body[:120]!r}", error_log)

            header = {key.lower(): value for key, value in headers.items()}
            if header.get("x-content-type-options") != "nosniff":
                return fail(f"missing nosniff header: {header}")

            env_status, _env_headers, env_body = request(base + "/.env")
            if env_status not in (403, 404):
                return fail(
                    f"dotfile returned {env_status}, body={env_body[:120]!r}", error_log
                )

            listing_status, _listing_headers, _listing_body = request(base + "/uploads/")
            if listing_status == 200:
                return fail("directory listing is enabled", error_log)

            print(f"apache {tested.stdout.strip() or 'config ok'} port={port}")
            print(
                f"index=200 nosniff=ok dotfile={env_status} "
                f"directory_listing={listing_status}"
            )
            print("APACHE_PACK_OK")
            return 0
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
