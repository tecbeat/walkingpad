"""Tests for scripts/bump_version.py.

The bump script mutates real repository files (`.version`,
`manifest.json`, `updater.yml`) and reads `$VERSION` from the
environment. Tests use monkeypatch + a tmp copy so nothing leaks into
the actual repo.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bump_version.py"


@pytest.fixture
def bump_module(monkeypatch, tmp_path):
    """Load scripts/bump_version.py against a temp repo layout.

    Reloads the module so ``_REPO_ROOT`` and friends resolve inside the
    tmp directory instead of the real repo. Also seeds the temp repo
    with the same starting state (.version=0.1.0, manifest.json with
    a matching version, no updater.yml).
    """
    repo = tmp_path
    (repo / ".version").write_text("0.1.0\n", encoding="utf-8")
    manifest_dir = repo / "custom_components" / "walkingpad"
    manifest_dir.mkdir(parents=True)
    manifest = {
        "domain": "walkingpad",
        "name": "KingSmith WalkingPad",
        "codeowners": ["@tecbeat"],
        "requirements": ["bleak-retry-connector==4.6.1"],
        "version": "0.1.0",
    }
    (manifest_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    # Load the script as a fresh module pointed at the tmp repo.
    spec = importlib.util.spec_from_file_location("bump_version_under_test", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bump_version_under_test"] = module
    spec.loader.exec_module(module)
    # Redirect the module's paths at the tmp repo.
    monkeypatch.setattr(module, "_REPO_ROOT", repo)
    monkeypatch.setattr(module, "_VERSION_FILE", repo / ".version")
    monkeypatch.setattr(
        module, "_MANIFEST_FILE", repo / "custom_components" / "walkingpad" / "manifest.json"
    )
    monkeypatch.setattr(module, "_UPDATER_FILE", repo / "updater.yml")
    return module, repo


def test_bump_writes_new_version(monkeypatch, bump_module):
    module, repo = bump_module
    monkeypatch.setenv("VERSION", "v0.2.0")

    module.main()

    assert (repo / ".version").read_text().strip() == "0.2.0"
    manifest = json.loads((repo / "custom_components/walkingpad/manifest.json").read_text())
    assert manifest["version"] == "0.2.0"

    updater = yaml.safe_load((repo / "updater.yml").read_text())
    assert updater["commits"][0]["branch"] == "automation/repository_updates"
    assert updater["commits"][0]["message"] == "chore(release): bump version to 0.2.0 [skip ci]"
    assert updater["merge_request"]["auto_merge"] is True


def test_bump_is_idempotent(monkeypatch, bump_module):
    module, repo = bump_module
    monkeypatch.setenv("VERSION", "v0.1.0")

    module.main()

    # No updater.yml written when nothing changed.
    assert not (repo / "updater.yml").exists()


def test_bump_strips_v_prefix_and_build_suffix(monkeypatch, bump_module):
    module, repo = bump_module
    monkeypatch.setenv("VERSION", "v0.2.0-158616")

    module.main()

    assert (repo / ".version").read_text().strip() == "0.2.0"


def test_bump_preserves_manifest_formatting(monkeypatch, bump_module):
    module, repo = bump_module
    manifest_path = repo / "custom_components/walkingpad/manifest.json"
    # Write with the same compact-array style the real repo uses.
    manifest_path.write_text(
        '{\n'
        '  "domain": "walkingpad",\n'
        '  "codeowners": ["@tecbeat"],\n'
        '  "requirements": ["bleak-retry-connector==4.6.1"],\n'
        '  "version": "0.1.0"\n'
        '}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VERSION", "v0.2.0")

    module.main()

    # Only the version line must differ; compact arrays must survive.
    result = manifest_path.read_text()
    assert '"codeowners": ["@tecbeat"]' in result
    assert '"requirements": ["bleak-retry-connector==4.6.1"]' in result
    assert '"version": "0.2.0"' in result


def test_bump_appends_to_existing_updater_yml(monkeypatch, bump_module):
    module, repo = bump_module
    # Simulate a templater that already wrote a plan (README-update).
    (repo / "updater.yml").write_text(
        yaml.safe_dump(
            {
                "commits": [
                    {
                        "branch": "automation/repository_updates",
                        "message": "chore: update default repository [skip ci]",
                        "actions": [{"action": "update", "path": "README.md"}],
                    }
                ],
                "merge_request": {"labels": ["automation"], "auto_merge": True},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VERSION", "v0.2.0")

    module.main()

    updater = yaml.safe_load((repo / "updater.yml").read_text())
    assert len(updater["commits"]) == 2
    assert updater["commits"][0]["actions"][0]["path"] == "README.md"
    assert updater["commits"][1]["message"].startswith("chore(release): bump version")


def test_bump_rejects_garbage_version(monkeypatch, bump_module):
    module, _ = bump_module
    monkeypatch.setenv("VERSION", "garbage")
    with pytest.raises(SystemExit):
        module.main()


def test_bump_rejects_missing_version(monkeypatch, bump_module):
    module, _ = bump_module
    monkeypatch.delenv("VERSION", raising=False)
    with pytest.raises(SystemExit):
        module.main()
