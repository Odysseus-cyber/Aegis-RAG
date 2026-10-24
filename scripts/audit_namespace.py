"""Audit the current deliverable; search terms are supplied by the operator."""
import argparse
import json
import subprocess
import zipfile
from pathlib import Path


def audit(root, paths, terms):
    terms = [term.casefold() for term in terms]
    findings = []
    for relative in sorted(set(paths)):
        path = root / relative
        if not path.is_file():
            continue
        parts = [("path", relative)]
        if path.is_symlink():
            parts.append(("link", str(path.readlink())))
        if path.suffix.lower() in {".pptx", ".docx", ".xlsx", ".zip"}:
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    parts.append((name, name + "\n" + archive.read(name).decode("utf-8", errors="ignore")))
        else:
            parts.append(("content", path.read_bytes().decode("utf-8", errors="ignore")))
        for location, content in parts:
            if any(term in content.casefold() for term in terms):
                # Do not print matching content: local material can contain private data.
                findings.append({"path": relative, "location": location})
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--term", action="append", required=True)
    parser.add_argument("--extra", action="append", default=[])
    args = parser.parse_args()
    if any(not term for term in args.term):
        parser.error("Search terms must not be empty")
    root = args.root.resolve()
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    for extra in args.extra:
        candidate = (root / extra).resolve()
        if not candidate.is_relative_to(root):
            parser.error("Extra paths must stay inside the deliverable directory")
        items = candidate.rglob("*") if candidate.is_dir() else [candidate]
        paths.extend(str(p.relative_to(root)) for p in items if p.is_file())
    findings = audit(root, [p for p in paths if p], args.term)
    print(json.dumps({"status": "failed" if findings else "passed", "findings": findings}, indent=2))
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
