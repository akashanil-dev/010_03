"""Server resource overview: totals, the TallyTime / AI model split, GPU detection and access. Run: pytest -q"""

import subprocess

from app import system
from tests.test_api import client, signed_up


def test_sample_reports_whole_machine_and_our_share():
    system.sample()   # the first per-process reading only sets a starting point
    s = system.sample()
    assert 0 <= s["cpu"]["percent"] <= 100 and s["cpu"]["cores"] >= 1
    assert 0 < s["ram"]["used_gb"] <= s["ram"]["total_gb"]
    assert s["ram"]["tallytime_gb"] > 0                       # this test process counts as TallyTime
    assert s["cpu"]["tallytime"] <= s["cpu"]["percent"]


def test_no_gpu(monkeypatch):
    monkeypatch.setattr(system, "_gpu_tool", None)
    assert system.gpu() is None and system.sample()["gpu"] is None


def test_nvidia_gpu_is_read(monkeypatch):
    monkeypatch.setattr(system, "_gpu_tool", "/usr/bin/nvidia-smi")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout="NVIDIA L4, 37, 4096, 23034\n"))
    assert system.gpu() == {"name": "NVIDIA L4", "percent": 37.0, "used_gb": 4.0, "total_gb": 22.5}


def test_broken_gpu_tool_counts_as_no_gpu(monkeypatch):
    monkeypatch.setattr(system, "_gpu_tool", "/usr/bin/nvidia-smi")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 9, stdout=""))
    assert system.gpu() is None


def test_overview_needs_login():
    assert client().get("/api/system").status_code == 401
    s = signed_up("Asha", "asha@example.com").get("/api/system").json()
    assert set(s) == {"at", "cpu", "ram", "gpu"}
