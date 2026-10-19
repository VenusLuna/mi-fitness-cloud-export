#!/usr/bin/env python3
"""Conservative publication check. Never print matching secret values."""
from __future__ import annotations
import argparse, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP_LEVEL = {"README.md", "SECURITY.md", "THIRD_PARTY.md", "LICENSE", ".gitignore",
             "cloud_export_web.py", "poll_once.py", "parse_health.py", "fds_tools.py",
             "requirements.txt", "requirements-fds.txt"}
DEPLOY = {"deploy/mi-fitness-sync.service", "deploy/mi-fitness-sync.timer"}
SKIP_DIRS = {".git", ".venv", "__pycache__", "private", "state", "data", "exports", "reports", "artifacts"}


def allowed_path(name: str) -> bool:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        return False
    if name in TOP_LEVEL or name in DEPLOY or name in {".githooks/pre-commit", "scripts/check_publish.py"}:
        return True
    if len(path.parts) != 2:
        return False
    return ((path.parts[0] == "docs" and path.suffix == ".md") or
            (path.parts[0] == "tests" and path.suffix == ".py" and
             (path.name.startswith("test_") or path.name == "__init__.py")))


def scan_text(text: str) -> list[str]:
    rules = [
        ("personal-absolute-path", r"/(?:Users|home)/[^\s/]+"),
        ("ipv4-address", r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
        ("private-key-block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        ("github-token", r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
        ("aws-access-key", r"\bAKIA[A-Z0-9]{16}\b"),
        ("email-address", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        ("authorization-value", r"(?i)\bBearer\s+[A-Za-z0-9._~-]{16,}"),
        ("signed-download-url", r"https://[^\s\"<>]+[?&](?:Signature|GalaxyAccessKeyId|Expires)="),
    ]
    issues = [name for name, pattern in rules if re.search(pattern, text)]
    assignment = r"(?i)[\"'](?:service_token|serviceToken|ssecurity|pass_token|auth_key|obj_key)[\"']\s*:\s*[\"']([^\"']+)[\"']"
    # The only fixed credential-like test literals accepted by this project.
    synthetic = {"FIXTURE", "FAKE_TOKEN", "SYNTHETIC", "Zml4dHVyZQ=="}
    if any(m.group(1) not in synthetic for m in re.finditer(assignment, text)):
        issues.append("literal-credential-value")
    return issues


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="read exact Git index, not working copies")
    args = parser.parse_args()
    if args.staged:
        names = [s.decode() for s in git("ls-files", "-z").split(b"\0") if s]
    else:
        names = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
                 if not any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts) and (p.is_file() or p.is_symlink())]
    problems = []
    for name in sorted(names):
        path = ROOT / name
        if not allowed_path(name):
            problems.append((name, "path-not-in-publication-allowlist"))
            continue
        if args.staged:
            mode = git("ls-files", "--stage", "--", name).split(None, 1)[0]
            if mode not in (b"100644", b"100755"):
                problems.append((name, "non-regular-git-entry"))
                continue
            data = git("show", ":" + name)
        else:
            if path.is_symlink():
                problems.append((name, "symlink-not-allowed"))
                continue
            data = path.read_bytes()
        if len(data) > 512 * 1024:
            problems.append((name, "oversize-file"))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append((name, "non-utf8-file"))
            continue
        problems.extend((name, reason) for reason in scan_text(text))
    for name, reason in problems:
        print(f"BLOCKED {name}: {reason}", file=sys.stderr)
    if problems:
        return 1
    print(f"PASS: {len(names)} method/code files; no blocked paths or configured secret patterns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
