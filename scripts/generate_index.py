#!/usr/bin/env python3

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import html
import json
from pathlib import Path
import re
import shutil

MANIFEST_NAME = "wheels.json"
REPO_URL_PREFIX = "https://github.com"
ARTIFACT_KIND_ORDER = {"wheel": 0, "sdist": 1}


@dataclass(frozen=True)
class ArtifactEntry:
    filename: str
    package: str
    version: str
    size_bytes: int
    sha256: str
    url: str
    kind: str


def canonicalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_manifest(root: Path) -> tuple[str, list[ArtifactEntry]]:
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        return "", []

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo = str(manifest.get("repo", "")).strip()
    artifact_entries = []

    for kind, key in (("wheel", "wheels"), ("sdist", "sdists")):
        for item in manifest.get(key, []):
            filename = str(item.get("filename", "")).strip()
            release_tag = str(item.get("release_tag", "")).strip()
            package = canonicalize_package_name(str(item.get("package", "")).strip())
            version = str(item.get("version", "")).strip()
            size_bytes = int(item.get("size_bytes", 0))
            sha256 = str(item.get("sha256", "")).strip()

            if repo:
                url = f"{REPO_URL_PREFIX}/{repo}/releases/download/{release_tag}/{filename}"
            else:
                url = ""

            if filename and package and version and sha256 and release_tag:
                artifact_entries.append(
                    ArtifactEntry(
                        filename=filename,
                        package=package,
                        version=version,
                        size_bytes=size_bytes,
                        sha256=sha256,
                        url=url,
                        kind=kind,
                    )
                )

    artifact_entries.sort(
        key=lambda entry: (
            entry.package,
            entry.version,
            ARTIFACT_KIND_ORDER[entry.kind],
            entry.filename,
        )
    )
    return repo, artifact_entries


def bytes_to_human(value: int) -> str:
    suffixes = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for suffix in suffixes:
        if size < 1024 or suffix == suffixes[-1]:
            return f"{size:.1f} {suffix}" if suffix != "B" else f"{int(size)} {suffix}"
        size /= 1024
    return f"{value} B"


def render_index(artifacts: list[ArtifactEntry]) -> str:
    grouped: dict[str, list[ArtifactEntry]] = defaultdict(list)
    for artifact in artifacts:
        grouped[artifact.package].append(artifact)

    lines: list[str] = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        "  <title>whl.knaebel.dev</title>",
        "  <style>",
        "    body { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; max-width: 920px; margin: 2rem auto; padding: 0 1rem; line-height: 1.4; }",
        "    h1 { margin-bottom: 0.25rem; }",
        "    .meta { color: #5f6368; font-size: 0.95rem; margin-bottom: 1.5rem; }",
        "    h2 { margin-top: 2rem; margin-bottom: 0.25rem; }",
        "    ul { padding-left: 1.25rem; }",
        "    li { margin: 0.5rem 0; }",
        "    .details { color: #5f6368; font-size: 0.9rem; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <h1>Python Packages</h1>",
        '  <p class="meta">Use with <code>pip install --no-index --find-links https://whl.knaebel.dev/ PACKAGE==VERSION</code></p>',
    ]

    if not artifacts:
        lines.append("  <p>No package files published yet.</p>")
    else:
        for package in sorted(grouped):
            entries = grouped[package]
            lines.append(f"  <h2 id=\"{html.escape(package)}\">{html.escape(package)}</h2>")
            lines.append("  <ul>")
            for artifact in entries:
                filename = html.escape(artifact.filename)
                url = html.escape(artifact.url)
                size = html.escape(bytes_to_human(artifact.size_bytes))
                version = html.escape(artifact.version)
                sha = html.escape(artifact.sha256)
                kind = html.escape(artifact.kind)
                lines.append(
                    f"    <li><a href=\"{url}#sha256={sha}\">{filename}</a> "
                    f"<span class=\"details\">{kind}, version {version}, {size}</span></li>"
                )
            lines.append("  </ul>")

    lines.extend(["</body>", "</html>", ""])
    return "\n".join(lines)


def build_dist(root: Path) -> int:
    repo, artifacts = load_manifest(root)
    if artifacts and not repo:
        raise SystemExit(f"{MANIFEST_NAME} must include a non-empty repo field.")
    dist = root / "dist"

    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True, exist_ok=True)

    index_html = render_index(artifacts)
    (dist / "index.html").write_text(index_html, encoding="utf-8")
    return len(artifacts)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    artifact_count = build_dist(root)
    print(f"Generated dist/ with {artifact_count} artifact(s).")


if __name__ == "__main__":
    main()
