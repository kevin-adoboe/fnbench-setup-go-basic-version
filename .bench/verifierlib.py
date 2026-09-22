"""
Shared helpers for task verifiers.

STDLIB ONLY. A verifier is designed to run as the final step of the CI job that the
agent configured, inside whatever container that job uses, so it cannot assume pyyaml
or any other third-party package is installed.

## What a verifier is for

It answers one question: **is the world in the state the task asked for?** It probes
the live environment and the workspace. It never greps the agent's config for an
expected command, never compares against a reference solution, and never rewards the
mere presence of the string `setup-go` or `setup-node`. Whether the intended Function
was used is recorded separately by the runner as a diagnostic (see
`runner/function_usage.py`), and it is not an input to success.

## Check naming convention, consistent across all tasks

    ci_*       the CI configuration exists and is valid — part of the task goal
               ("configure CI so ..."), but only presence/validity, never text
    runtime_*  the language runtime is present and is the version the task requires
    deps_*     dependencies are materialised and match the lockfile
    build_*    the project builds
    test_*     the project's tests pass, and actually ran

## Check states

True / False / None. `None` means "could not be evaluated here" (e.g. the `circleci`
CLI is absent so config validity could not be checked). A required check that comes
back `None` fails the run — a verifier must never silently pass because it could not
look. Optional checks that come back `None` are reported and ignored.

## Output contract

    {"task_id": ..., "success": bool, "checks": {name: bool|null},
     "required": [names], "details": {...}, "environment": {...}}

Exit status is 0 when `success` is true, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_TIMEOUT = 600


def run(cmd, cwd=None, env=None, timeout=DEFAULT_TIMEOUT):
    """Run cmd (list) and return (returncode, stdout+stderr). Never raises."""
    merged = dict(os.environ)
    if env:
        merged.update({k: str(v) for k, v in env.items()})
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=merged,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(cmd)}: timed out after {timeout}s"
    except Exception as exc:  # pragma: no cover - defensive
        return 1, f"{' '.join(cmd)}: {exc}"


def which(binary):
    return shutil.which(binary)


class Verifier:
    """Accumulates checks and emits the structured result."""

    def __init__(self, task_id, workspace):
        self.task_id = task_id
        self.workspace = Path(workspace).resolve()
        self.checks = {}
        self.required = []
        self.details = {}
        self.started = time.time()

    # -- recording ---------------------------------------------------------

    def check(self, name, value, required=True, detail=None):
        """Record a check. value may be True, False or None (not evaluable)."""
        self.checks[name] = value
        if required and name not in self.required:
            self.required.append(name)
        if detail is not None:
            self.details[name] = detail
        return value

    def note(self, key, value):
        self.details[key] = value

    # -- generic probes ----------------------------------------------------

    def ci_config(self, required=True):
        """`ci_config_present` + `ci_config_valid`.

        Validity is structural only: the config parses and the CircleCI CLI accepts
        it. Nothing here inspects which steps or commands the agent chose.
        """
        cfg = self.workspace / ".circleci" / "config.yml"
        alt = self.workspace / ".circleci" / "config.yaml"
        path = cfg if cfg.exists() else (alt if alt.exists() else None)
        self.check("ci_config_present", path is not None, required=required,
                   detail=str(path.relative_to(self.workspace)) if path else
                   "no .circleci/config.yml or .circleci/config.yaml")
        if path is None:
            self.check("ci_config_valid", False, required=required,
                       detail="skipped: no config to validate")
            return None
        if not which("circleci"):
            self.check("ci_config_valid", None, required=required,
                       detail="circleci CLI not on PATH, cannot validate")
            return path
        rc, out = run(["circleci", "config", "validate", str(path)], cwd=self.workspace,
                      timeout=120)
        self.check("ci_config_valid", rc == 0, required=required,
                   detail=out.strip()[:400])
        return path

    def tool_version(self, name, cmd, pattern, want, required=True):
        """Probe a tool's self-reported version against a regex + expected prefix.

        `runtime_<name>_available` and `runtime_<name>_version` are recorded.
        """
        avail = which(cmd[0]) is not None
        self.check(f"runtime_{name}_available", avail, required=required,
                   detail=which(cmd[0]) or f"{cmd[0]} not on PATH")
        if not avail:
            self.check(f"runtime_{name}_version", False, required=required,
                       detail=f"{cmd[0]} not on PATH, cannot report a version")
            return None
        rc, out = run(cmd, cwd=self.workspace, timeout=120)
        m = re.search(pattern, out)
        got = m.group(0) if m else None
        ok = bool(got) and got.startswith(want)
        self.check(f"runtime_{name}_version", ok, required=required,
                   detail={"reported": out.strip()[:200], "parsed": got, "wanted_prefix": want})
        return got

    def command_succeeds(self, check_name, cmd, cwd=None, env=None, required=True,
                         timeout=DEFAULT_TIMEOUT, must_contain=None, must_not_contain=None):
        """Run a command and require exit 0, plus optional output assertions."""
        rc, out = run(cmd, cwd=cwd or self.workspace, env=env, timeout=timeout)
        ok = rc == 0
        detail = {"cmd": " ".join(cmd), "exit": rc, "output_tail": out.strip()[-1500:]}
        if ok and must_contain:
            missing = [s for s in must_contain if s not in out]
            if missing:
                ok = False
                detail["missing_from_output"] = missing
        if ok and must_not_contain:
            present = [s for s in must_not_contain if s in out]
            if present:
                ok = False
                detail["unexpected_in_output"] = present
        self.check(check_name, ok, required=required, detail=detail)
        return rc, out

    def path_exists(self, check_name, relative, required=True, kind="any"):
        p = self.workspace / relative
        ok = p.is_dir() if kind == "dir" else (p.is_file() if kind == "file" else p.exists())
        self.check(check_name, ok, required=required,
                   detail={"path": str(relative), "exists": p.exists(), "expected_kind": kind})
        return ok

    # -- emit --------------------------------------------------------------

    def environment(self):
        env = {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cwd": str(self.workspace),
            "tools": {},
        }
        for binary, args in (("go", ["version"]), ("node", ["--version"]),
                             ("npm", ["--version"]), ("pnpm", ["--version"]),
                             ("yarn", ["--version"]), ("bun", ["--version"]),
                             ("circleci", ["version"])):
            if which(binary):
                _, out = run([binary] + args, timeout=60)
                env["tools"][binary] = out.strip().splitlines()[0][:120] if out.strip() else ""
            else:
                env["tools"][binary] = None
        return env

    def result(self):
        required_ok = all(self.checks.get(n) is True for n in self.required)
        optional_false = [n for n, v in self.checks.items()
                          if n not in self.required and v is False]
        return {
            "task_id": self.task_id,
            "success": bool(required_ok),
            "checks": self.checks,
            "required": self.required,
            "optional_failed": optional_false,
            "details": self.details,
            "environment": self.environment(),
            "verifier_seconds": round(time.time() - self.started, 2),
        }

    def emit(self):
        res = self.result()
        print(json.dumps(res, indent=2, sort_keys=True))
        return 0 if res["success"] else 1


def parse_args(task_id):
    """Standard verifier CLI: --workspace (default cwd)."""
    import argparse

    ap = argparse.ArgumentParser(description=f"verifier for {task_id}")
    ap.add_argument("--workspace", default=os.environ.get("BENCH_WORKSPACE", "."),
                    help="repo root to verify (default: $BENCH_WORKSPACE or cwd)")
    return ap.parse_args()


def locate_lib():
    """Let a staged copy of a verifier import this module. Used by verify.py files."""
    here = Path(__file__).resolve().parent
    return str(here)


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None
