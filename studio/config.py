from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
COMFY_DIR = ROOT / "vendor" / "ComfyUI"
COMFY_MODELS = COMFY_DIR / "models"

CACHE = ROOT / "cache"
COMFY_INPUT = CACHE / "comfy_input"
COMFY_OUTPUT = CACHE / "comfy_output"
UPLOADS = CACHE / "uploads"
LOGS = CACHE / "logs"
OUTPUTS = ROOT / "outputs" / "studio"
DB_PATH = ROOT / "outputs" / "studio.sqlite3"

STUDIO_HOST = os.environ.get("STUDIO_HOST", "127.0.0.1")
STUDIO_PORT = int(os.environ.get("STUDIO_PORT", "8800"))
COMFY_PORT = int(os.environ.get("STUDIO_COMFY_PORT", "8189"))
COMFY_URL = f"http://127.0.0.1:{COMFY_PORT}"

for d in (COMFY_INPUT, COMFY_OUTPUT, UPLOADS, LOGS, OUTPUTS):
    d.mkdir(parents=True, exist_ok=True)
