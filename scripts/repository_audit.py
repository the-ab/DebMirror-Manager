#!/usr/bin/env python3
"""Fail when release/source trees contain common secret or runtime artifacts."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}
ALLOWED_FILES = {".env.example", ".gitkeep"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".dmmbackup", ".pem", ".key", ".p12", ".pfx"}
FORBIDDEN_NAMES = {".env", "install-config.env", "docker-compose.override.yml"}
PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----"),
    "GitHub token": re.compile(rb"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"),
    "AWS access key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "Slack token": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "generic bearer token": re.compile(rb"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._~-]{20,}"),
}


def iter_files():
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.is_file() and not path.is_symlink():
            yield path



def audit_release_version(findings: list[str]) -> None:
    version_path = ROOT / "VERSION"
    if not version_path.is_file():
        # The reduced app/repository policy snapshot intentionally has no release files.
        return
    version = version_path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        findings.append(f"invalid VERSION value: {version!r}")
        return

    expected = {
        "README.md": (f"Current version: **{version}**", f"debmirror-manager-v{version}.zip"),
        "README.de.md": (f"Aktuelle Version: **{version}**", f"debmirror-manager-v{version}.zip"),
    }
    for rel_name, markers in expected.items():
        path = ROOT / rel_name
        if not path.is_file():
            findings.append(f"missing release-version file: {rel_name}")
            continue
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in text:
                findings.append(f"version mismatch in {rel_name}: missing {marker!r}")

    for rel_name in ("RELEASE_NOTES.md", "RELEASE_NOTES.de.md"):
        path = ROOT / rel_name
        if not path.is_file():
            findings.append(f"missing release notes: {rel_name}")
            continue
        match = re.search(r"^## v([^\s]+)", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
        if not match or match.group(1) != version:
            found = match.group(1) if match else "missing"
            findings.append(f"version mismatch in {rel_name}: top release is {found}, expected {version}")

    main_source = ROOT / "app" / "main.py"
    if main_source.is_file():
        main_text = main_source.read_text(encoding="utf-8")
        if main_text.count(f"## v{version}\\n") < 2:
            findings.append("built-in DE/EN release-notes fallback does not match VERSION")

    update_script = ROOT / "update.sh"
    if update_script.is_file():
        update_text = update_script.read_text(encoding="utf-8")
        if f"${{PROJECT_NAME}}-vX.Y.Z.zip" not in update_text:
            findings.append("update.sh help must use the version-neutral vX.Y.Z package example")
        if re.search(r"\$\{PROJECT_NAME\}-v\d+\.\d+\.\d+\.zip", update_text):
            findings.append("update.sh help contains a hard-coded release package version")

    docs_dir = ROOT / "app" / "docs"
    if docs_dir.is_dir():
        for rel_name in ("README.md", "README.de.md", "RELEASE_NOTES.md", "RELEASE_NOTES.de.md"):
            source = ROOT / rel_name
            copy = docs_dir / rel_name
            if source.is_file() and copy.is_file() and source.read_bytes() != copy.read_bytes():
                findings.append(f"internal documentation copy differs from {rel_name}: app/docs/{rel_name}")


def main() -> int:
    findings: list[str] = []
    audit_release_version(findings)
    for path in iter_files():
        rel = path.relative_to(ROOT)
        if path.name in ALLOWED_FILES:
            continue
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(f"forbidden release artifact: {rel}")
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            findings.append(f"unreadable file: {rel}: {exc}")
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(data):
                findings.append(f"possible {label}: {rel}")
    if findings:
        print("Repository audit failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Repository audit passed: no forbidden runtime artifacts or common secret patterns found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
