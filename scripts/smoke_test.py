#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _cli_base() -> list[str]:
    command = shutil.which("scholar-vault")
    if command:
        return [command]
    return [sys.executable, "-c", "from scholar_vault.cli import main; main()"]


def _run(args: list[str], *, json_output: bool = False) -> dict | None:
    command = [*_cli_base(), *args]
    result = subprocess.run(command, check=False, text=True, capture_output=True)
    if result.returncode != 0:
        sys.stderr.write(f"Command failed: {' '.join(command)}\n")
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    if json_output:
        return json.loads(result.stdout)
    return None


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="scholar-vault-smoke-") as tmpdir:
        vault = Path(tmpdir) / "vault"
        vault_arg = ["--vault", str(vault)]

        _run(["init", *vault_arg])
        _run(
            [
                "query",
                "create",
                "Smoke-test research question?",
                *vault_arg,
                "--slug",
                "smoke-query",
                "--json",
            ],
            json_output=True,
        )
        first_bases = _run(["bases", "rebuild", *vault_arg, "--json"], json_output=True)
        second_bases = _run(["bases", "rebuild", *vault_arg, "--json"], json_output=True)
        if second_bases and second_bases.get("changed") != 0:
            raise SystemExit("Repeated bases rebuild was not deterministic.")
        if first_bases is None:
            raise SystemExit("Bases rebuild did not return JSON.")

        queue = _run(
            [
                "queue",
                "add",
                *vault_arg,
                "--kind",
                "lint_fix",
                "--title",
                "Smoke queue item",
                "--required-evidence",
                "none",
                "--success-criteria",
                "Created by smoke test.",
                "--stable-key",
                "smoke:test-queue",
                "--json",
            ],
            json_output=True,
        )
        _run(["queue", "list", *vault_arg, "--json"], json_output=True)
        _run(
            [
                "operations",
                "log",
                *vault_arg,
                "--kind",
                "smoke",
                "--message",
                "Smoke operation.",
                "--command",
                "scripts/smoke_test.py",
                "--check",
                "smoke",
                "--json",
            ],
            json_output=True,
        )
        _run(
            [
                "feedback",
                "rate",
                "smoke-target",
                *vault_arg,
                "--target-type",
                "tool_behavior",
                "--verdict",
                "needs_fix",
                "--notes",
                "Smoke feedback.",
                "--queue-item",
                str(queue["id"] if queue else ""),
                "--json",
            ],
            json_output=True,
        )
        _run(["feedback", "report", *vault_arg, "--json"], json_output=True)
        _run(["lint-wiki", *vault_arg, "--json"], json_output=True)
        _run(["eval", "list", *vault_arg, "--json"], json_output=True)

        print(f"Smoke test passed: {vault}")


if __name__ == "__main__":
    main()
