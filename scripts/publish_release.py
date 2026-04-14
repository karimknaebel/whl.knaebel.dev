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
SDIST_SUFFIXES = (".tar.gz", ".zip")
GITHUB_REPO_RE = re.compile(r"^(?:git@github\.com:|https://github\.com/)([^/]+/[^/]+?)(?:\.git)?$")


@dataclass(frozen=True)
class ArtifactRecord:
    filename: str
    package: str
    version: str
    size_bytes: int
    sha256: str
    release_tag: str
    kind: str


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


def parse_sdist_filename(filename: str) -> tuple[str, str]:
    for suffix in SDIST_SUFFIXES:
        if filename.endswith(suffix):
            stem = filename[: -len(suffix)]
            break
    else:
        raise SystemExit(f"Unsupported distribution filename: {filename}")

    package, sep, version = stem.rpartition("-")
    if not sep or not package or not version:
        raise SystemExit(f"Unrecognized sdist filename: {filename}")

    return canonicalize_package_name(package), version


def collect_artifacts(paths: list[Path], tag: str) -> list[ArtifactRecord]:
    records: list[ArtifactRecord] = []
    for path in paths:
        package: str
        version: str
        kind: str

        match = WHEEL_NAME_RE.match(path.name)
        if match:
            package = canonicalize_package_name(match.group("name"))
            version = match.group("version")
            kind = "wheel"
        else:
            package, version = parse_sdist_filename(path.name)
            kind = "sdist"

        records.append(
            ArtifactRecord(
                filename=path.name,
                package=package,
                version=version,
                size_bytes=path.stat().st_size,
                sha256=sha256_file(path),
                release_tag=tag,
                kind=kind,
            )
        )
    return records


def ensure_repo(manifest_repo: str, cli_repo: str) -> str:
    if manifest_repo and cli_repo and manifest_repo != cli_repo:
        raise SystemExit(f"Manifest repo is {manifest_repo}, but CLI repo is {cli_repo}.")
    return cli_repo or manifest_repo


def create_release(tag: str, title: str, notes: str, artifact_paths: list[Path]) -> None:
    cmd = ["gh", "release", "create", tag, *[str(path) for path in artifact_paths]]
    cmd.extend(["--title", title, "--notes", notes])
    subprocess.run(cmd, check=True)


def iter_manifest_artifacts(manifest: dict):
    yield from manifest.get("wheels", [])
    yield from manifest.get("sdists", [])


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish wheel and sdist files to a GitHub release.")
    parser.add_argument("artifacts", nargs="+", help="Distribution files to publish.")
    parser.add_argument("--tag", required=True, help="Release tag to create.")
    parser.add_argument("--title", help="Release title (defaults to tag).")
    parser.add_argument("--repo", help="GitHub repo in owner/name format.")
    parser.add_argument("--notes", default="Automated package release.", help="Release notes.")
    args = parser.parse_args()

    artifact_paths = [Path(path) for path in args.artifacts]
    missing = [str(path) for path in artifact_paths if not path.exists()]
    if missing:
        raise SystemExit(f"Missing distribution files: {', '.join(missing)}")

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

    records = collect_artifacts(artifact_paths, args.tag)
    existing = {
        (entry.get("release_tag"), entry.get("filename"))
        for entry in iter_manifest_artifacts(manifest)
    }
    for record in records:
        key = (record.release_tag, record.filename)
        if key in existing:
            raise SystemExit(f"Artifact already recorded in manifest: {record.filename} ({record.release_tag})")

    create_release(args.tag, args.title or args.tag, args.notes, artifact_paths)

    manifest["repo"] = repo
    manifest.setdefault("wheels", [])
    manifest.setdefault("sdists", [])
    for record in records:
        target = manifest["wheels"] if record.kind == "wheel" else manifest["sdists"]
        target.append(
            {
                "filename": record.filename,
                "package": record.package,
                "version": record.version,
                "size_bytes": record.size_bytes,
                "sha256": record.sha256,
                "release_tag": record.release_tag,
            }
        )

    manifest["wheels"].sort(key=lambda entry: (entry["package"], entry["version"], entry["filename"]))
    manifest["sdists"].sort(key=lambda entry: (entry["package"], entry["version"], entry["filename"]))
    write_manifest(manifest_path, manifest)

    subprocess.run([sys.executable, str(root / "scripts" / "generate_index.py")], check=True)


if __name__ == "__main__":
    main()
