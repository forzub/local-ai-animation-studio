"""Local AI Studio: FastAPI-сервер (API + веб-интерфейс)."""
import asyncio
import hashlib
import io
import re
import shutil
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from . import config, jobs, recipes
from .comfy import engine

STATIC = config.ROOT / "studio" / "static"


@asynccontextmanager
async def lifespan(app):
    jobs.init_db()
    worker = asyncio.create_task(jobs.worker())
    warm = asyncio.create_task(engine.ensure_running())  # движок стартует заранее, ошибки увидит первая задача
    yield
    worker.cancel()
    warm.cancel()
    engine.stop()


app = FastAPI(title="Local AI Studio", lifespan=lifespan)


class RefIn(BaseModel):
    upload_id: str
    role: str


class JobIn(BaseModel):
    model: str
    mode: str
    prompt: str = ""
    refs: list[RefIn] = []
    aspect: str = "1:1"
    megapixels: float = Field(1.0, gt=0.05, le=4.0)
    count: int = Field(1, ge=1, le=8)
    seed: Optional[int] = None
    steps: Optional[int] = Field(None, ge=1, le=100)
    strength: Optional[float] = Field(None, ge=0.05, le=1.0)
    ref_megapixels: Optional[float] = Field(None, gt=0.05, le=2.0)
    role_prompts: bool = True
    # видео
    duration: Optional[float] = None
    fps: Optional[int] = None
    resolution: Optional[str] = None
    camera: Optional[str] = None
    negative: Optional[str] = None


@app.get("/api/models")
def list_models():
    return {"models": [r.info() for r in recipes.RECIPES.values()], "roles": recipes.ROLES, "aspects": recipes.ASPECTS}


@app.get("/api/status")
async def status():
    alive = await engine.alive()
    out = {"engine": "running" if alive else "starting"}
    if alive:
        dev = (await engine.system_stats())["devices"][0]
        # "cuda:0 Quadro RTX 3000 : cudaMallocAsync" -> "Quadro RTX 3000"
        out["gpu"] = {"name": re.sub(r"^cuda:\d+\s*", "", dev["name"]).split(" : ")[0],
                      "vram_total": dev["vram_total"], "vram_free": dev["vram_free"]}
    with jobs.db() as con:
        out["queued"] = con.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
    return out


@app.post("/api/engine/free")
async def free_engine():
    await engine.free_memory()
    return {"ok": True}


def _store_image(data: bytes):
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
        im.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "Файл не является изображением")
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    upload_id = hashlib.sha256(data).hexdigest()[:20]
    path = config.UPLOADS / f"{upload_id}.png"
    if not path.exists():
        im.save(path)
    return {"upload_id": upload_id, "width": im.width, "height": im.height, "url": f"/uploads/{upload_id}"}


@app.post("/api/uploads")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 64 * 1024 * 1024:
        raise HTTPException(413, "Файл больше 64 МБ")
    return _store_image(data)


class FromOutput(BaseModel):
    job_id: str
    file: str


@app.post("/api/uploads/from-output")
def upload_from_output(body: FromOutput):
    return _store_image(_output_path(body.job_id, body.file).read_bytes())


@app.get("/uploads/{upload_id}")
def get_upload(upload_id: str):
    p = jobs.upload_path(upload_id)
    if not p:
        raise HTTPException(404)
    return FileResponse(p)


@app.post("/api/jobs")
def create_job(body: JobIn):
    p = body.model_dump()
    try:
        job_id = jobs.create_job(p)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": job_id}


@app.get("/api/jobs")
def list_jobs(limit: int = 60, before: Optional[float] = None, favorites: bool = False):
    q, args = "SELECT * FROM jobs WHERE 1=1", []
    if before:
        q += " AND created < ?"
        args.append(before)
    if favorites:
        q += " AND favorite=1"
    q += " ORDER BY created DESC LIMIT ?"
    args.append(min(limit, 200))
    with jobs.db() as con:
        return {"jobs": [jobs.row_to_job(r) for r in con.execute(q, args)]}


def _get_job(job_id):
    with jobs.db() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Задача не найдена")
    return jobs.row_to_job(row)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return _get_job(job_id)


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str):
    return {"ok": jobs.cancel_job(job_id)}


@app.post("/api/jobs/{job_id}/favorite")
def favorite(job_id: str, value: bool = True):
    _get_job(job_id)
    with jobs.db() as con:
        con.execute("UPDATE jobs SET favorite=? WHERE id=?", (int(value), job_id))
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = _get_job(job_id)
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "Сначала отмените задачу")
    d = jobs.job_dir(job)
    if d.exists() and config.OUTPUTS in d.parents:
        shutil.rmtree(d)
    with jobs.db() as con:
        con.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    return {"ok": True}


def _output_path(job_id, name):
    job = _get_job(job_id)
    if name not in {o["file"] for o in job["outputs"]} and name != "job.json":
        raise HTTPException(404)
    p = jobs.job_dir(job) / name
    if not p.exists():
        raise HTTPException(404, "Файл результата удалён с диска")
    return p


@app.get("/files/{job_id}/{name}")
def get_output(job_id: str, name: str, download: bool = False):
    p = _output_path(job_id, name)
    return FileResponse(p, filename=f"{job_id}-{name}" if download else None)


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
