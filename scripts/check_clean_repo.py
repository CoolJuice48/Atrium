#!/usr/bin/env python3
"""
Verify the repo tree is clean for committing.
Exits 0 if OK, 1 if problematic paths would be committed.

Usage: python scripts/check_clean_repo.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Paths that should NOT be committed
FORBIDDEN_PATTERNS = [
    "textbook_index",
    ".venv",
    "node_modules",
    ".next",
    "__pycache__",
    ".pytest_cache",
    "*.pkl",
    "*.faiss",
    "converted/",
    "pdfs/",
]

# Paths we explicitly allow (exceptions)
ALLOWED = [
    "eval/golden_sets/",
    "docs/",
]

# Max size (bytes) for a single file we'd flag
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB


def get_tracked_files():
    """List files that would be committed (staged + unstaged in working tree)."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "-u"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if out.returncode != 0:
            return []
    except FileNotFoundError:
        return []
    files = set()
    for line in out.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            path = parts[-1]
            if path and not path.startswith(".."):
                files.add(path)
    # Also consider what's in the index
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if out.returncode == 0:
        for p in out.stdout.strip().splitlines():
            if p:
                files.add(p)
    return files


def check_path(path: str) -> list[str]:
    """Return list of violation messages for this path."""
    violations = []
    path_lower = path.lower().replace("\\", "/")
    for bad in FORBIDDEN_PATTERNS:
        if bad.startswith("*"):
            if path_lower.endswith(bad[1:]):
                violations.append(f"Matches forbidden pattern: {bad}")
        elif bad in path_lower or path_lower.startswith(bad):
            if not any(a in path_lower for a in ALLOWED):
                violations.append(f"Matches forbidden: {bad}")
    return violations


def main():
    if not (ROOT / ".git").exists():
        print("Not a git repo. Skipping check.")
        return 0

    files = get_tracked_files()
    errors = []
    for f in sorted(files):
        vs = check_path(f)
        if vs:
            errors.append((f, vs))
        # Check size
        p = ROOT / f
        if p.is_file() and p.stat().st_size > MAX_FILE_BYTES:
            size_mb = p.stat().st_size / (1024 * 1024)
            errors.append((f, [f"Large file ({size_mb:.1f} MB) – consider git-lfs or exclude"]))

    if errors:
        print("check_clean_repo: problematic paths:")
        for path, msgs in errors:
            print(f"  {path}")
            for m in msgs:
                print(f"    - {m}")
        return 1
    print("check_clean_repo: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
