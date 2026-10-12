"""Server resource overview for the top bar: CPU, RAM and GPU of the whole machine, split into TallyTime, the AI
model (Ollama) and everything else.

A background thread samples every few seconds, so a page view never waits for a measurement. Only totals and the
three-way split are shared with the browser: no process names, paths or host details.
"""

import os
import shutil
import subprocess
import threading
import time

import psutil

INTERVAL = 2.0
GB = 1024 ** 3

_latest: dict | None = None
_lock = threading.Lock()
_procs: dict[int, psutil.Process] = {}   # kept between samples so per-process CPU can be measured
_gpu_tool = shutil.which("nvidia-smi")


def _group(p: psutil.Process, ours: set[int]) -> str:
    if p.pid in ours:
        return "tallytime"
    try:
        name = p.name().lower()
    except psutil.Error:
        return "other"
    return "model" if name.startswith("ollama") else "other"


def _tallytime_pids() -> set[int]:
    """This web app, the worker and the worker's reader process."""
    ours = {os.getpid()}
    for p in psutil.process_iter(["cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if "app.worker" in cmd or "app.main:app" in cmd:
            ours.add(p.pid)
            try:
                ours.update(c.pid for c in p.children(recursive=True))
            except psutil.Error:
                pass
    return ours


def gpu() -> dict | None:
    """The first NVIDIA GPU's usage, or None when the server has none."""
    if not _gpu_tool:
        return None
    try:
        out = subprocess.run([_gpu_tool, "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout
        name, util, used, total = [x.strip() for x in out.splitlines()[0].split(",")]
        return {"name": name, "percent": float(util), "used_gb": round(float(used) / 1024, 1),
                "total_gb": round(float(total) / 1024, 1)}
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def sample() -> dict:
    cores = psutil.cpu_count() or 1
    ours = _tallytime_pids()
    cpu = {"tallytime": 0.0, "model": 0.0}
    ram = {"tallytime": 0, "model": 0}
    alive = set()
    for p in psutil.process_iter():
        alive.add(p.pid)
        group = _group(p, ours)
        if group == "other":
            continue
        proc = _procs.setdefault(p.pid, p)
        try:
            cpu[group] += proc.cpu_percent(None) / cores   # since the previous sample, as a share of the machine
            ram[group] += proc.memory_info().rss
        except psutil.Error:
            pass
    for pid in set(_procs) - alive:
        del _procs[pid]
    vm = psutil.virtual_memory()
    total_cpu = psutil.cpu_percent(None)
    used = vm.total - vm.available
    return {
        "at": time.time(),
        "cpu": {"percent": round(total_cpu, 1), "cores": cores,
                "tallytime": round(min(cpu["tallytime"], total_cpu), 1), "model": round(min(cpu["model"], total_cpu), 1)},
        "ram": {"percent": round(vm.percent, 1), "used_gb": round(used / GB, 1), "total_gb": round(vm.total / GB, 1),
                "tallytime_gb": round(ram["tallytime"] / GB, 1), "model_gb": round(ram["model"] / GB, 1)},
        "gpu": gpu(),
    }


def latest() -> dict | None:
    with _lock:
        return _latest


def _run() -> None:
    global _latest
    psutil.cpu_percent(None)   # the first reading only sets the starting point
    time.sleep(INTERVAL)
    while True:
        try:
            snap = sample()
            with _lock:
                _latest = snap
        except Exception:
            pass
        time.sleep(INTERVAL)


def start() -> None:
    threading.Thread(target=_run, daemon=True, name="tallytime-system").start()
