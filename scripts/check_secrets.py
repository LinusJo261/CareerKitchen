"""Check tracked file names and common real credential formats without printing secrets."""

import re
import subprocess
import sys
from pathlib import Path


def main() -> int:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    )
    problems = []
    patterns = [
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(rb"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{30,}\b"),
        re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(rb"\bsb_secret_[A-Za-z0-9_-]{20,}\b"),
    ]
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        path = Path(raw.decode("utf-8"))
        if path.name.startswith(".env") and path.name != ".env.example":
            problems.append(str(path))
        if path.is_file() and path.stat().st_size < 2_000_000:
            content = path.read_bytes()
            if any(pattern.search(content) for pattern in patterns):
                problems.append(str(path))
    if problems:
        print("Potential secret material in repository files: " + ", ".join(sorted(set(problems))))
        return 1
    print("No tracked environment files or recognized private-key/token patterns in repository source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
