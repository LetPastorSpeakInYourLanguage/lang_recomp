"""Every test runs against throwaway settings and job folders.

The app reads its settings (and so its job folders: Google Drive, this PC's worker
folder) from a file fixed when the settings module loads. Without this, a test that
queues a job would write it into the owner's real Drive, where Colab would run it.
"""
import json

import pytest

from app import project, settings


@pytest.fixture(autouse=True)
def isolated_job_folders(tmp_path_factory, monkeypatch):
    base = tmp_path_factory.mktemp("roots")
    s = {"roots": [{"id": "colab", "name": "Colab (test)", "kind": "colab", "path": str(base / "colab")},
                   {"id": "local", "name": "This PC (test)", "kind": "local", "path": str(base / "local")}],
         "active": "colab"}
    path = base / "settings.json"
    path.write_text(json.dumps(s), encoding="utf-8")
    monkeypatch.setattr(settings, "PATH", path)
    monkeypatch.setattr(project, "_queues", {})
    yield base
