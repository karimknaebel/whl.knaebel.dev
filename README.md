# whl.knaebel.dev

Static wheel hosting for `pip --find-links` using GitHub Releases + GitHub Pages.

## Publish flow

1. Prepare wheel files (local paths, not committed).
2. Create a GitHub Release and update the index:

```bash
python scripts/publish_release.py --tag wheels-YYYY-MM-DD path/to/*.whl
```

3. Deploy `dist/` to GitHub Pages.

GitHub Pages config (Actions-based):

1. Build command: `UV_CACHE_DIR=/tmp/uv-cache uv run scripts/generate_index.py`
2. Build output directory: `dist`
3. `wheels.json` must contain the repo in `owner/name` format

## Repo layout

1. `wheels.json` stores the published wheel metadata.
2. `dist/` is the generated GitHub Pages site.
3. `scripts/publish_release.py` creates a release and updates the index.
4. `scripts/generate_index.py` rebuilds the index from `wheels.json`.

## Install

```bash
pip install --no-index --find-links https://whl.knaebel.dev/ PACKAGE==VERSION
```

Package names are normalized per pip rules, so a wheel like
`gloss_rs-0.8.0-...whl` is installable as `gloss-rs==0.8.0`.
