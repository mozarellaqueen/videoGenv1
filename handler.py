"""RunPod-Serverless-Handler für das KI-Studio.

Ersetzt den Standard-Handler von worker-comfyui, weil der keine Video-Ausgaben (VHS "gifs") zurückgibt
und Eingaben nur als Base64-Bilder (max. 10 MB) annimmt.

Eingabe (job["input"]):
{
  "workflow": {...},                                # ComfyUI-Workflow im API-Format
  "inputs":   [{"name": "x.mp4", "url": "https://..."}],   # werden in ComfyUI/input geladen
  "uploads":  [{"slot": 0, "url": "https://...presigned PUT..."}],
  "prefer":   "video"                               # Videos zuerst hochladen
}
Ausgabe: {"files": [{"name": "...mp4", "slot": 0, "size": 123}], "prompt_id": "...", "seconds": 42.1}
"""
from __future__ import annotations

import os
import shutil
import time
import traceback
import uuid
from pathlib import Path

import requests
import runpod

COMFY = os.environ.get("COMFY_HOST", "127.0.0.1:8188")
COMFY_DIR = Path(os.environ.get("COMFY_DIR", "/comfyui"))
INPUT_DIR = COMFY_DIR / "input"
OUTPUT_DIR = COMFY_DIR / "output"
MAX_WAIT = int(os.environ.get("STUDIO_MAX_WAIT_SECONDS", "3600"))
VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".gif"}


def wait_for_comfy(timeout: int = 600) -> None:
    t = time.time()
    while time.time() - t < timeout:
        try:
            if requests.get(f"http://{COMFY}/system_stats", timeout=5).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("ComfyUI ist nicht gestartet (Timeout)")


def download_inputs(items: list[dict]) -> list[Path]:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for it in items or []:
        name = os.path.basename(it["name"])
        dest = INPUT_DIR / name
        with requests.get(it["url"], stream=True, timeout=300) as r:
            r.raise_for_status()
            with dest.open("wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        paths.append(dest)
    return paths


def queue(workflow: dict) -> str:
    r = requests.post(f"http://{COMFY}/prompt", json={"prompt": workflow, "client_id": str(uuid.uuid4())}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"ComfyUI hat den Workflow abgelehnt: {r.text[:1500]}")
    data = r.json()
    if data.get("node_errors"):
        raise RuntimeError(f"Fehler in Nodes: {str(data['node_errors'])[:1500]}")
    return data["prompt_id"]


def wait_history(prompt_id: str, job: dict) -> dict:
    t = time.time()
    last_note = 0.0
    while time.time() - t < MAX_WAIT:
        r = requests.get(f"http://{COMFY}/history/{prompt_id}", timeout=30)
        if r.status_code == 200 and prompt_id in (data := r.json()):
            h = data[prompt_id]
            st = h.get("status", {})
            if st.get("status_str") == "error":
                msgs = [m for m in st.get("messages", []) if m and m[0] == "execution_error"]
                detail = msgs[-1][1] if msgs else st
                if isinstance(detail, dict):
                    detail = f"{detail.get('node_type')}: {detail.get('exception_message')}"
                raise RuntimeError(f"ComfyUI-Ausführungsfehler: {str(detail)[:1500]}")
            if st.get("completed") or h.get("outputs"):
                return h.get("outputs", {})
        if time.time() - last_note > 30:
            runpod.serverless.progress_update(job, f"rendert … {int(time.time() - t)} s")
            last_note = time.time()
        time.sleep(2)
    raise RuntimeError("Zeitlimit beim Rendern überschritten")


def collect(outputs: dict, prefer: str, workflow: dict | None = None) -> list[Path]:
    files: list[Path] = []
    # Ausgabe des Nodes mit Titel OUT_VIDEO kommt immer zuerst (nicht z. B. eine Pose-Vorschau)
    main_ids = {nid for nid, n in (workflow or {}).items()
                if str((n.get("_meta") or {}).get("title", "")).strip().upper() == "OUT_VIDEO"}
    ordered = sorted(outputs.items(), key=lambda kv: kv[0] not in main_ids)
    for _nid, node_out in ordered:
        for key in ("gifs", "videos", "images", "audio"):
            for item in node_out.get(key, []) or []:
                if not isinstance(item, dict) or item.get("type") == "temp":
                    continue
                if item.get("fullpath"):
                    p = Path(item["fullpath"])
                else:
                    p = OUTPUT_DIR / item.get("subfolder", "") / item.get("filename", "")
                if p.is_file() and p not in files:
                    files.append(p)
    if prefer == "video" and not main_ids:
        files.sort(key=lambda p: (p.suffix.lower() not in VIDEO_EXT, -p.stat().st_mtime))
    return files


def upload(files: list[Path], slots: list[dict]) -> list[dict]:
    out = []
    for f, slot in zip(files, slots):
        with f.open("rb") as fh:
            r = requests.put(slot["url"], data=fh, timeout=600)
        r.raise_for_status()
        out.append({"name": f.name, "slot": slot["slot"], "size": f.stat().st_size})
    return out


def cleanup(paths: list[Path]) -> None:
    for p in paths:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    if OUTPUT_DIR.exists():
        for child in OUTPUT_DIR.iterdir():
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)


def ensure_volume_dirs() -> None:
    """Zielordner der Symlinks auf dem Network Volume anlegen (sonst schlagen Auto-Downloads fehl)."""
    vol = Path("/runpod-volume")
    if vol.is_dir():
        for sub in ("models/detection", "models/sam2", "cache/vfi_ckpts"):
            (vol / sub).mkdir(parents=True, exist_ok=True)


def handler(job: dict) -> dict:
    inp = job.get("input") or {}
    if "workflow" not in inp:
        return {"error": "input.workflow fehlt"}
    started = time.time()
    inputs: list[Path] = []
    produced: list[Path] = []
    try:
        ensure_volume_dirs()
        wait_for_comfy()
        inputs = download_inputs(inp.get("inputs", []))
        runpod.serverless.progress_update(job, "Workflow startet")
        prompt_id = queue(inp["workflow"])
        outputs = wait_history(prompt_id, job)
        produced = collect(outputs, inp.get("prefer", "video"), inp["workflow"])
        if not produced:
            return {"error": "Workflow lief durch, hat aber keine Datei gespeichert (Video-Combine mit save_output=true?)"}
        slots = inp.get("uploads") or []
        if not slots:
            return {"error": "keine Upload-Ziele (uploads) übergeben"}
        files = upload(produced, slots)
        return {"files": files, "prompt_id": prompt_id, "seconds": round(time.time() - started, 1)}
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)[:2000]}
    finally:
        cleanup(inputs + produced)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
