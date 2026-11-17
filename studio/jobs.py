"""Очередь задач, история (SQLite) и GPU-воркер. Задачи выполняются строго по одной."""
import asyncio
import json
import random
import shutil
import sqlite3
import time
import traceback
import uuid
from datetime import datetime

from PIL import Image

from . import config, recipes
from .comfy import engine, ComfyError, Cancelled

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created REAL NOT NULL,
    started REAL,
    finished REAL,
    status TEXT NOT NULL,          -- queued | running | done | failed | cancelled
    kind TEXT NOT NULL,
    model TEXT NOT NULL,
    mode TEXT NOT NULL,
    params TEXT NOT NULL,
    outputs TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    favorite INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created);
"""


def db():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript(SCHEMA)
        con.execute("UPDATE jobs SET status='failed', error='Прервано перезапуском студии', finished=? WHERE status='running'", (time.time(),))


def row_to_job(row):
    j = dict(row)
    j["params"] = json.loads(j["params"])
    j["outputs"] = json.loads(j["outputs"])
    j["favorite"] = bool(j["favorite"])
    j.update(live.get(j["id"], {}))
    return j


live = {}  # id -> {progress, stage} для выполняющейся задачи
_cancel = set()
_wakeup = asyncio.Event()


def upload_path(upload_id):
    if not upload_id or not upload_id.isalnum():
        return None
    p = config.UPLOADS / f"{upload_id}.png"
    return p if p.exists() else None


def create_job(p):
    recipe = recipes.get(p["model"])
    if recipe is None:
        raise ValueError(f"Неизвестная модель {p['model']}")
    if recipe.missing_files():
        raise ValueError(f"Не хватает файлов модели: {', '.join(recipe.missing_files())}")
    for r in p["refs"]:
        if not upload_path(r["upload_id"]):
            raise ValueError("Референс не найден, загрузите его заново")
    err = recipe.validate(p)
    if err:
        raise ValueError(err)
    if p.get("seed") in (None, "", -1):
        p["seed"] = random.randint(0, 2**48)
    job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    with db() as con:
        con.execute("INSERT INTO jobs (id, created, status, kind, model, mode, params) VALUES (?,?,?,?,?,?,?)",
                    (job_id, time.time(), "queued", recipe.kind, recipe.id, p["mode"], json.dumps(p, ensure_ascii=False)))
    _wakeup.set()
    return job_id


def cancel_job(job_id):
    with db() as con:
        cur = con.execute("UPDATE jobs SET status='cancelled', finished=? WHERE id=? AND status='queued'", (time.time(), job_id))
        if cur.rowcount:
            return True
        row = con.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row and row["status"] == "running":
        _cancel.add(job_id)
        return True
    return False


def job_dir(job):
    return config.OUTPUTS / job["id"][:8] / job["id"]


def _set(job_id, **fields):
    keys = ", ".join(f"{k}=?" for k in fields)
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for v in fields.values()]
    with db() as con:
        con.execute(f"UPDATE jobs SET {keys} WHERE id=?", (*vals, job_id))


async def _run(job):
    job_id, p = job["id"], job["params"]
    recipe = recipes.get(job["model"])
    out_dir = job_dir(job)
    out_dir.mkdir(parents=True, exist_ok=True)

    refs = []
    for r in p["refs"]:
        src = upload_path(r["upload_id"])
        dst = config.COMFY_INPUT / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
        with Image.open(src) as im:
            refs.append({"file": dst.name, "role": r["role"], "width": im.width, "height": im.height})

    count = max(1, int(p.get("count") or 1))
    outputs, graphs, metas = [], [], []
    state = live[job_id]
    has_keyframe = hasattr(recipe, "keyframe")

    def collect(result, meta, role=None):
        files = []
        for node_out in result.values():
            for key in ("images", "videos", "gifs"):
                for f in node_out.get(key, []):
                    if f.get("type") != "output":
                        continue
                    src = config.COMFY_OUTPUT / f.get("subfolder", "") / f["filename"]
                    name = f"{len(outputs) + 1:02d}{src.suffix}"
                    shutil.move(src, out_dir / name)
                    out = {"file": name, "seed": meta["seed"], "width": meta["width"], "height": meta["height"],
                           "media": "video" if src.suffix.lower() in (".mp4", ".webm", ".mkv") else "image"}
                    if role:
                        out["role"] = role
                    outputs.append(out)
                    files.append(out_dir / name)
        _set(job_id, outputs=outputs)
        return files

    for i in range(count):
        # этапы варианта: [ключевой кадр], основной граф
        stages = []
        kf = recipe.keyframe(p, refs, i) if has_keyframe else None
        if kf:
            stages.append(("keyframe", kf))
        n_stages = len(stages) + 1
        var_refs = refs

        for s in range(n_stages):
            if s < len(stages):
                role, (graph, meta) = stages[s]
            else:
                role, (graph, meta) = None, recipe.build(p, var_refs, i)
            graphs.append(graph)
            metas.append(meta)
            label = ("Ключевой кадр: " if role == "keyframe" else "")

            def on_progress(stage, step, total, i=i, s=s, label=label):
                if stage:
                    state["stage"] = label + stage + (f" · вариант {i + 1}/{count}" if count > 1 else "")
                if step is not None and total:
                    state["progress"] = (i + (s + step / total) / n_stages) / count

            result = await engine.run(graph, on_progress, lambda: job_id in _cancel)
            files = collect(result, meta, role)
            if role == "keyframe":
                if not files:
                    raise ComfyError("Ключевой кадр не был сохранён")
                dst = config.COMFY_INPUT / f"{job_id}-kf{i}.png"
                shutil.copy2(files[0], dst)
                var_refs = [{"file": dst.name, "role": "start", "width": meta["width"], "height": meta["height"]}]
        state["progress"] = (i + 1) / count

    meta = metas[-1]
    sidecar = {"job": job_id, "model": recipe.id, "model_files": recipe.files, "license": recipe.license,
               "params": p, "prompt_sent": meta.get("prompt_sent"), "stage_meta": metas, "outputs": outputs, "graphs": graphs,
               "created": datetime.fromtimestamp(job["created"]).isoformat()}
    (out_dir / "job.json").write_text(json.dumps(sidecar, ensure_ascii=False, indent=1), encoding="utf-8")
    return outputs


async def worker():
    while True:
        with db() as con:
            row = con.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
        if row is None:
            _wakeup.clear()
            await _wakeup.wait()
            continue
        job = row_to_job(row)
        live[job["id"]] = {"progress": 0.0, "stage": "Запуск движка"}
        _set(job["id"], status="running", started=time.time())
        try:
            await _run(job)
            _set(job["id"], status="done", finished=time.time())
        except Cancelled:
            _set(job["id"], status="cancelled", finished=time.time())
        except ComfyError as e:
            _set(job["id"], status="failed", error=str(e), finished=time.time())
        except Exception as e:  # любая ошибка задачи не должна останавливать очередь
            traceback.print_exc()
            _set(job["id"], status="failed", error=f"{type(e).__name__}: {e}", finished=time.time())
        finally:
            live.pop(job["id"], None)
            _cancel.discard(job["id"])
