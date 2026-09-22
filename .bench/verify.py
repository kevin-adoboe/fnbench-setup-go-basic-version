#!/usr/bin/env python3
"""Verifier for setup-go/basic-version.

Runs as the final step of the job the agent configured, so the three checks probe the
environment that job actually produced:

    runtime_available   a `go` binary resolves on PATH
    runtime_version     it reports the go1.22.x the task asked for
    build_success       `go build ./...` compiles every package in the module

It never reads the agent's configuration and never looks for `setup-go`. An agent that
installs Go some other way and lands in the same state passes. Whether the intended
Function was used is a separate diagnostic recorded by the runner.
"""

import sys
from pathlib import Path


def _load_lib():
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        for cand in (parent / "verifierlib.py", parent / "runner" / "verifierlib.py"):
            if cand.exists():
                sys.path.insert(0, str(cand.parent))
                return
    sys.exit("verifierlib.py not found (expected beside this file or in <repo>/runner/)")


_load_lib()
import verifierlib as vl  # noqa: E402

TASK_ID = "setup-go/basic-version"
WANT_GO_PREFIX = "go1.22"


def main():
    args = vl.parse_args(TASK_ID)
    v = vl.Verifier(TASK_ID, args.workspace)

    go = vl.which("go")
    v.check("runtime_available", go is not None,
            detail={"resolved": go} if go else {"resolved": None,
                                                "reason": "no `go` on PATH"})

    if go:
        rc, out = vl.run(["go", "version"], cwd=v.workspace, timeout=120)
        reported = out.strip()
        version = None
        for token in reported.split():
            if token.startswith("go1."):
                version = token
                break
        v.check("runtime_version", bool(version) and version.startswith(WANT_GO_PREFIX),
                detail={"reported": reported[:200], "parsed": version,
                        "wanted_prefix": WANT_GO_PREFIX})
    else:
        v.check("runtime_version", False,
                detail={"reason": "cannot report a version without a runtime"})

    # The fixture uses the `min` builtin, so this also fails for a real reason on a
    # toolchain older than 1.21 rather than only failing the version comparison.
    v.command_succeeds("build_success", ["go", "build", "./..."], timeout=900)

    return v.emit()


if __name__ == "__main__":
    sys.exit(main())
