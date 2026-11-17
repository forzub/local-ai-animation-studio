"""Скрытый движок ComfyUI: запуск дочернего процесса и выполнение API-графов."""
import asyncio
import json
import subprocess
import sys
import time
import uuid

import aiohttp

from . import config

NODE_STAGES = {
    "UNETLoader": "Загрузка модели",
    "UnetLoaderGGUF": "Загрузка модели",
    "CLIPLoader": "Загрузка текстового энкодера",
    "VAELoader": "Загрузка VAE",
    "CLIPTextEncode": "Кодирование промпта",
    "VAEEncode": "Кодирование референсов",
    "SamplerCustomAdvanced": "Генерация",
    "KSampler": "Генерация",
    "VAEDecode": "Декодирование",
    "SaveImage": "Сохранение",
    "SaveVideo": "Сохранение",
}


class ComfyError(Exception):
    def __init__(self, msg, oom=False):
        super().__init__(msg)
        self.oom = oom


class Cancelled(Exception):
    pass


class ComfyEngine:
    def __init__(self):
        self.proc = None
        self.client_id = "studio-" + uuid.uuid4().hex[:8]
        self.session = None
        self.log_file = None

    async def _session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=5))
        return self.session

    async def alive(self):
        try:
            s = await self._session()
            async with s.get(config.COMFY_URL + "/system_stats", timeout=aiohttp.ClientTimeout(total=3)) as r:
                return r.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def system_stats(self):
        s = await self._session()
        async with s.get(config.COMFY_URL + "/system_stats") as r:
            return await r.json()

    async def ensure_running(self):
        if await self.alive():
            return
        if self.proc is None or self.proc.poll() is not None:
            self.log_file = open(config.LOGS / "comfy.log", "ab")
            args = [
                sys.executable, "main.py",
                "--listen", "127.0.0.1", "--port", str(config.COMFY_PORT),
                "--lowvram", "--disable-auto-launch", "--disable-api-nodes",
                "--input-directory", str(config.COMFY_INPUT),
                "--output-directory", str(config.COMFY_OUTPUT),
            ]
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self.proc = subprocess.Popen(args, cwd=config.COMFY_DIR, stdout=self.log_file,
                                         stderr=subprocess.STDOUT, creationflags=flags)
        deadline = time.time() + 180
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise ComfyError(f"Движок ComfyUI завершился при запуске (код {self.proc.returncode}), см. cache/logs/comfy.log")
            if await self.alive():
                return
            await asyncio.sleep(1)
        raise ComfyError("Движок ComfyUI не ответил за 3 минуты, см. cache/logs/comfy.log")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.session and not self.session.closed:
            asyncio.get_event_loop().create_task(self.session.close())

    async def interrupt(self):
        s = await self._session()
        async with s.post(config.COMFY_URL + "/interrupt", json={}) as r:
            await r.read()

    async def free_memory(self):
        """Выгрузить все модели из VRAM. Флаг обрабатывается воркером ComfyUI сразу, если очередь пуста."""
        await self.ensure_running()
        s = await self._session()
        async with s.post(config.COMFY_URL + "/free", json={"unload_models": True, "free_memory": True}) as r:
            await r.read()
        await asyncio.sleep(2)

    async def run(self, graph, on_progress, is_cancelled):
        """Выполнить API-граф. on_progress(stage, step, total). Возвращает outputs из history."""
        await self.ensure_running()
        s = await self._session()
        ws_url = config.COMFY_URL.replace("http", "ws") + f"/ws?clientId={self.client_id}"
        # Без heartbeat: во время тяжёлых узлов (VAE 720p) движок может долго не отвечать на ping.
        ws = await s.ws_connect(ws_url, heartbeat=None, max_msg_size=0)
        try:
            async with s.post(config.COMFY_URL + "/prompt", json={"prompt": graph, "client_id": self.client_id}) as r:
                body = await r.json()
                if r.status != 200:
                    raise ComfyError(_format_validation_error(body))
            prompt_id = body["prompt_id"]
            cancel_sent = False
            quiet = 0.0
            while True:
                if is_cancelled() and not cancel_sent:
                    await self.interrupt()
                    cancel_sent = True
                if ws.closed:
                    # Соединение оборвалось: если процесс жив — переподключаемся, иначе это падение движка.
                    if self.proc is not None and self.proc.poll() is not None:
                        raise ComfyError(f"Движок ComfyUI аварийно завершился (код {self.proc.returncode}), см. cache/logs/comfy.log")
                    await asyncio.sleep(2)
                    try:
                        ws = await s.ws_connect(ws_url, heartbeat=None, max_msg_size=0)
                    except aiohttp.ClientError:
                        # свой процесс проверяется через poll() выше; чужой (запущенный вручную) — по ответу API
                        if self.proc is None and not await self.alive():
                            raise ComfyError("Движок ComfyUI перестал отвечать, см. cache/logs/comfy.log")
                        continue
                    quiet = 30.0  # сразу сверить историю: сообщения о завершении могли потеряться
                if quiet >= 30.0:
                    quiet = 0.0
                    done = await self._history_status(prompt_id)
                    if done is not None:
                        break
                try:
                    msg = await ws.receive(timeout=1.0)
                except asyncio.TimeoutError:
                    quiet += 1.0
                    continue
                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                    continue  # обработается веткой ws.closed
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue  # бинарные превью
                data = json.loads(msg.data)
                t, d = data.get("type"), data.get("data", {})
                if d.get("prompt_id") not in (None, prompt_id):
                    continue
                if t == "executing" and d.get("node"):
                    cls = graph.get(d["node"], {}).get("class_type", "")
                    on_progress(NODE_STAGES.get(cls, "Обработка"), None, None)
                elif t == "progress":
                    on_progress(None, d.get("value"), d.get("max"))
                elif t == "execution_error":
                    raise ComfyError(_format_exec_error(d), oom=_is_oom(d))
                elif t == "execution_interrupted":
                    raise Cancelled()
                elif t == "execution_success" or (t == "executing" and d.get("node") is None):
                    break
        finally:
            await ws.close()
        # Сообщения о завершении приходят до записи истории (task_done) — ждём, пока она появится.
        hist = {}
        for _ in range(120):
            hist = await self._history(prompt_id)
            if hist.get("status", {}).get("completed") is not None:
                break
            await asyncio.sleep(0.5)
        else:
            raise ComfyError("Движок не записал результат задачи в историю за 60 секунд")
        status = hist.get("status", {})
        if status.get("status_str") == "error":
            for kind, d in status.get("messages", []):
                if kind == "execution_error":
                    raise ComfyError(_format_exec_error(d), oom=_is_oom(d))
                if kind == "execution_interrupted":
                    raise Cancelled()
            raise ComfyError("Движок сообщил об ошибке выполнения")
        if cancel_sent:
            raise Cancelled()
        return hist.get("outputs", {})

    async def _history(self, prompt_id):
        s = await self._session()
        async with s.get(config.COMFY_URL + f"/history/{prompt_id}") as r:
            return (await r.json()).get(prompt_id, {})

    async def _history_status(self, prompt_id):
        """None — ещё выполняется; иначе статус из истории движка."""
        try:
            hist = await self._history(prompt_id)
        except aiohttp.ClientError:
            return None
        return hist.get("status") if hist.get("status", {}).get("completed") is not None else None


def _is_oom(d):
    return "out of memory" in d.get("exception_message", "").lower() or "OutOfMemory" in d.get("exception_type", "")


def _format_exec_error(d):
    msg = d.get("exception_message", "").strip()
    if _is_oom(d):
        return "Не хватило видеопамяти. Уменьшите разрешение, длительность или число референсов."
    return f"{d.get('node_type', '')}: {msg}"[:1500]


def _format_validation_error(body):
    err = body.get("error", {})
    parts = [err.get("message", "Ошибка проверки графа")]
    for node_id, info in (body.get("node_errors") or {}).items():
        for e in info.get("errors", []):
            parts.append(f"{info.get('class_type', node_id)}: {e.get('message')} {e.get('details', '')}")
    return "; ".join(parts)[:1500]


engine = ComfyEngine()
