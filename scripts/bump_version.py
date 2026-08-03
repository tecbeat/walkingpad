"""Sync the semantic version across the repository's version-carrying files.

Reads ``VERSION`` from the environment (populated by the teccave versioner
job as ``vMAJOR.MINOR.PATCH`` on ``main`` and ``vMAJOR.MINOR.PATCH-BUILD``
on feature branches), strips the leading ``v`` and any ``-BUILD`` suffix
so the resulting string is a plain SemVer, and writes it into:

- ``.version`` at the repo root, the human-readable single source of truth
- ``custom_components/walkingpad/manifest.json`` under the ``version`` key,
  which Home Assistant and HACS read to display the integration version

Then appends a commit action to ``updater.yml`` so the teccave ``updater``
job on ``main`` commits both files back to the default branch via an
automation MR.

Idempotent: if the target version already matches, no files are touched
and no updater action is written.

Runs both locally (with ``VERSION`` exported) and inside the pipeline
container. Uses only the standard library plus ``PyYAML`` (already
provided by the teccave core image).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VERSION_FILE = _REPO_ROOT / ".version"
_MANIFEST_FILE = _REPO_ROOT / "custom_components" / "walkingpad" / "manifest.json"
_UPDATER_FILE = _REPO_ROOT / "updater.yml"

_SEMVER_RE = re.compile(r"^v?(\d+\.\d+\.\d+)(?:[-.].*)?$")


def _normalise(raw: str) -> str:
    """Turn ``v1.2.3`` or ``v1.2.3-1234`` into ``1.2.3``.

    Anything else raises SystemExit — the pipeline must not silently
    write a garbage version.
    """
    match = _SEMVER_RE.match(raw.strip())
    if match is None:
        sys.exit(f"bump_version: {raw!r} is not a recognised SemVer string")
    return match.group(1)


def _write_version_file(version: str) -> bool:
    current = _VERSION_FILE.read_text(encoding="utf-8").strip() if _VERSION_FILE.exists() else ""
    if current == version:
        return False
    _VERSION_FILE.write_text(f"{version}\n", encoding="utf-8")
    return True


_MANIFEST_VERSION_RE = re.compile(r'("version"\s*:\s*")([^"]+)(")')


def _write_manifest(version: str) -> bool:
    """Replace only the ``version`` value, byte-for-byte preserving everything else.

    A full ``json.dumps`` round-trip is tempting but reformats compact
    arrays like ``"codeowners": ["@tecbeat"]`` to multi-line, which
    would land a noisy whitespace diff in the version-bump commit. A
    targeted regex substitution keeps the diff exactly one line.
    """
    text = _MANIFEST_FILE.read_text(encoding="utf-8")
    # Verify the current value with a real JSON parse — if the file is
    # not valid JSON we want to fail loudly, not silently patch.
    current = json.loads(text).get("version")
    if current == version:
        return False
    new_text, n = _MANIFEST_VERSION_RE.subn(rf"\g<1>{version}\g<3>", text, count=1)
    if n != 1:
        sys.exit("bump_version: could not locate version field in manifest.json")
    _MANIFEST_FILE.write_text(new_text, encoding="utf-8")
    return True


def _append_updater_plan(files: list[str], version: str) -> None:
    """Add a version-bump commit to updater.yml, preserving existing plans.

    The templater may have already written an updater.yml with its own
    ``chore: update default repository`` commit. We append a second
    entry so both changes land on ``main`` in one automation MR run,
    without stepping on the templater's action.
    """
    plan: dict = {"commits": [], "merge_request": {"labels": ["automation"], "auto_merge": True}}
    if _UPDATER_FILE.exists():
        loaded = yaml.safe_load(_UPDATER_FILE.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            plan["commits"] = loaded.get("commits") or []
            if "merge_request" in loaded:
                plan["merge_request"] = loaded["merge_request"]

    plan["commits"].append(
        {
            "branch": "automation/repository_updates",
            "message": f"chore(release): bump version to {version} [skip ci]",
            "actions": [{"action": "update", "path": path} for path in files],
        }
    )

    _UPDATER_FILE.write_text(
        yaml.safe_dump(plan, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def main() -> None:
    raw = os.environ.get("VERSION")
    if not raw:
        sys.exit("bump_version: VERSION environment variable is not set")
    version = _normalise(raw)

    changed: list[str] = []
    if _write_version_file(version):
        changed.append(".version")
    if _write_manifest(version):
        changed.append(_MANIFEST_FILE.relative_to(_REPO_ROOT).as_posix())

    if not changed:
        print(f"bump_version: already at {version}, nothing to do")
        return

    _append_updater_plan(changed, version)
    print(f"bump_version: updated {', '.join(changed)} to {version}")


if __name__ == "__main__":
    main()
