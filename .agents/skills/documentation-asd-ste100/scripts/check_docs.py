#!/usr/bin/env python3
"""Check maintnote documentation for ASD-STE100 compliance and broken links."""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOC_FILES = (
    Path("README.md"),
    Path("CONTRIBUTING.md"),
    Path("docs/index.md"),
    Path("docs/getting-started.md"),
    Path("docs/workflows.md"),
    Path("docs/security-and-transport.md"),
    Path("docs/specification-compliance.md"),
    Path("docs/api-reference.md"),
)

BANNED_PATTERNS = (
    r"\bensure\b",
    r"\bmultiple\b",
    r"\boften\b",
    r"\bpermit(s|ted)?\b",
    r"\bby hand\b",
    r"\bout of the box\b",
    r"\bincoming\b",
    r"\bauto-populat",
    r"\be\.g\.",
    r"\bi\.e\.",
    r"\betc\.",
    r"\bvia\b",
    r"\butilize\b",
    r"\bleverage\b",
    r"\bnotice(s)?\b",
    r"—",
    r"\bshould\b",
    r"\bmight\b",
    r"\bcould\b",
    r"\bwould\b",
)

MAX_DESCRIPTIVE_WORDS = 25


def slugify(heading: str) -> str:
    """Convert a Markdown heading into a MkDocs/GitHub anchor slug."""
    cleaned = re.sub(r"`([^`]*)`", r"\1", heading.lower())
    cleaned = re.sub(r"[^a-z0-9 -]", "", cleaned)
    return re.sub(r"\s+", "-", cleaned.strip())


def collect_headings(repo_root: Path) -> dict[Path, set[str]]:
    """Collect heading slugs for all checked Markdown files."""
    headings_by_file: dict[Path, set[str]] = {}
    for rel_path in DOC_FILES:
        full_path = (repo_root / rel_path).resolve()
        if not full_path.exists():
            continue
        in_code = False
        slugs: set[str] = set()
        for line in full_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if not in_code and line.startswith("#"):
                heading = re.sub(r"^#+\s*", "", line).strip()
                slugs.add(slugify(heading))
        headings_by_file[full_path] = slugs
    return headings_by_file


def check_docs(repo_root: Path) -> list[str]:
    """Return a list of ASD-STE100 and link issues across project docs."""
    headings_by_file = collect_headings(repo_root)
    issues: list[str] = []

    for rel_path in DOC_FILES:
        full_path = (repo_root / rel_path).resolve()
        if not full_path.exists():
            issues.append(f"{rel_path}: FILE MISSING")
            continue

        in_code = False
        for lineno, line in enumerate(full_path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue

            for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", line):
                target = match.group(1)
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path_part, _, anchor = target.partition("#")
                resolved = (full_path.parent / path_part).resolve() if path_part else full_path
                if not resolved.exists():
                    issues.append(f"{rel_path}:{lineno}: BROKEN LINK -> {target}")
                elif (
                    anchor
                    and resolved in headings_by_file
                    and anchor not in headings_by_file[resolved]
                ):
                    issues.append(f"{rel_path}:{lineno}: BROKEN ANCHOR -> {target}")

            plain = re.sub(r"`[^`]*`", "CODE", line)
            plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain).strip()
            if not plain or plain.startswith(("#", "|", "---", "!!!")):
                continue

            for pattern in BANNED_PATTERNS:
                if re.search(pattern, plain, flags=re.IGNORECASE):
                    issues.append(f"{rel_path}:{lineno}: BANNED({pattern}) -> {line.strip()}")

            body = re.sub(r"^(\s*[-*]|\s*\d+\.)\s+", "", plain)
            for sentence in re.split(r"(?<=[.!?])\s+", body):
                sentence = sentence.strip()
                if not sentence:
                    continue
                words = re.findall(r"[A-Za-z0-9_'-]+", sentence)
                if len(words) > MAX_DESCRIPTIVE_WORDS:
                    issues.append(f"{rel_path}:{lineno}: LONG({len(words)}w) -> {sentence}")

    return issues


def main() -> int:
    repo_root = Path.cwd()
    issues = check_docs(repo_root)
    print(f"Checked {len(DOC_FILES)} documentation files. Issues found: {len(issues)}")
    for issue in issues:
        print(f"  {issue}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
