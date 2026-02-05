#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

MANIFEST_NAME = "wheels.json"
WHEEL_NAME_RE = re.compile(
    r"^(?P<name>.+?)-(?P<version>[^-]+)(?:-(?P<build>\d[^-]*))?-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$"
)
GITHUB_REPO_RE = re.compile(r"^(?:git@github\.com:|https://github\.com/)([^/]+/[^/]+?)(?:\.git)?$")


@dataclass(frozen=True)
class WheelRecord:
    filename: str
    package: str
    version: str
    size_bytes: int
    sha256: str
    release_tag: str


def canonicalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def infer_repo_from_git() -> str:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return ""

    match = GITHUB_REPO_RE.match(result.stdout.strip())
    return match.group(1) if match else ""


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"repo": "", "wheels": []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def collect_wheels(paths: list[Path], tag: str) -> list[WheelRecord]:
    records: list[WheelRecord] = []
    for path in paths:
        match = WHEEL_NAME_RE.match(path.name)
        if not match:
            raise SystemExit(f"Unrecognized wheel filename: {path.name}")

        package = canonicalize_package_name(match.group("name"))
        version = match.group("version")
        records.append(
            WheelRecord(
                filename=path.name,
                package=package,
                version=version,
                size_bytes=path.stat().st_size,
                sha256=sha256_file(path),
                release_tag=tag,
            )
        )
    return records


def ensure_repo(manifest_repo: str, cli_repo: str) -> str:
    if manifest_repo and cli_repo and manifest_repo != cli_repo:
        raise SystemExit(f"Manifest repo is {manifest_repo}, but CLI repo is {cli_repo}.")
    return cli_repo or manifest_repo


def create_release(tag: str, title: str, notes: str, wheel_paths: list[Path]) -> None:
    cmd = ["gh", "release", "create", tag, *[str(path) for path in wheel_paths]]
    cmd.extend(["--title", title, "--notes", notes])
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish wheels to a GitHub release.")
    parser.add_argument("wheels", nargs="+", help="Wheel files to publish.")
    parser.add_argument("--tag", required=True, help="Release tag to create.")
    parser.add_argument("--title", help="Release title (defaults to tag).")
    parser.add_argument("--repo", help="GitHub repo in owner/name format.")
    parser.add_argument("--notes", default="Automated wheel release.", help="Release notes.")
    args = parser.parse_args()

    wheel_paths = [Path(path) for path in args.wheels]
    missing = [str(path) for path in wheel_paths if not path.exists()]
    if missing:
        raise SystemExit(f"Missing wheel files: {', '.join(missing)}")

    inferred_repo = infer_repo_from_git()
    repo = ensure_repo(args.repo or "", inferred_repo)
    if not repo:
        raise SystemExit("Could not infer repo. Pass --repo owner/name.")

    root = Path(__file__).resolve().parent.parent
    manifest_path = root / MANIFEST_NAME
    manifest = load_manifest(manifest_path)
    manifest_repo = str(manifest.get("repo", "")).strip()
    repo = ensure_repo(manifest_repo, repo)
    if not repo:
        raise SystemExit("Repo must be set in wheels.json or provided via --repo.")

    create_release(args.tag, args.title or args.tag, args.notes, wheel_paths)

    records = collect_wheels(wheel_paths, args.tag)
    existing = {
        (entry.get("release_tag"), entry.get("filename"))
        for entry in manifest.get("wheels", [])
    }
    for record in records:
        key = (record.release_tag, record.filename)
        if key in existing:
            raise SystemExit(f"Wheel already recorded in manifest: {record.filename} ({record.release_tag})")

    manifest["repo"] = repo
    manifest.setdefault("wheels", [])
    manifest["wheels"].extend(
        {
            "filename": record.filename,
            "package": record.package,
            "version": record.version,
            "size_bytes": record.size_bytes,
            "sha256": record.sha256,
            "release_tag": record.release_tag,
        }
        for record in records
    )

    manifest["wheels"].sort(key=lambda entry: (entry["package"], entry["version"], entry["filename"]))
    write_manifest(manifest_path, manifest)

    subprocess.run([sys.executable, str(root / "scripts" / "generate_index.py")], check=True)


if __name__ == "__main__":
    main()
