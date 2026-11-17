"""Wan 2.2 TI2V-5B (GGUF Q4_K_M): text-to-video и image-to-video (начальный кадр).

Модель сама не принимает референсы персонажа/окружения/стиля. Если они прикреплены,
задача выполняется в два этапа: Klein 4B строит ключевой кадр по референсам, Wan его оживляет.
"""
from .base import Recipe, size_for, size_like, role_prompt
from .klein import Klein4B

FPS = 24  # родная частота TI2V-5B

NEGATIVE = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，"
            "丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
            "静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走")

CAMERAS = {
    "": "Без указания",
    "static": "Статичная камера",
    "push_in": "Медленный наезд",
    "pull_out": "Медленный отъезд",
    "pan_left": "Панорама влево",
    "pan_right": "Панорама вправо",
    "orbit": "Облёт вокруг объекта",
    "tracking": "Следование за персонажем",
    "crane_up": "Подъём камеры (кран)",
    "handheld": "Ручная камера",
}
CAMERA_PROMPTS = {
    "static": "Static locked-off camera, no camera movement.",
    "push_in": "The camera slowly dollies in toward the subject.",
    "pull_out": "The camera slowly dollies out, revealing more of the scene.",
    "pan_left": "The camera pans slowly to the left.",
    "pan_right": "The camera pans slowly to the right.",
    "orbit": "The camera orbits smoothly around the subject.",
    "tracking": "Tracking shot: the camera follows the character as they move.",
    "crane_up": "Crane shot: the camera rises upward smoothly.",
    "handheld": "Handheld camera with subtle natural shake.",
}
# Целевое число пикселей кадра (кратность 32 у латента Wan 2.2)
RESOLUTIONS = {"draft": ("Черновик · ~640×352", 0.215), "sd": ("Стандарт · ~832×480", 0.38), "hd": ("720p · ~1280×704 (очень долго)", 0.86)}


class WanTI2V5B(Recipe):
    id = "wan2.2-ti2v-5b"
    name = "Wan 2.2 TI2V 5B (Q4)"
    kind = "video"
    modes = {"t2v": "Текст → видео", "i2v": "Изображение → видео"}
    files = ["unet/Wan2.2-TI2V-5B-Q4_K_M.gguf", "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "vae/wan2.2_vae.safetensors"]
    max_refs = 6
    ref_roles = ["start", "character", "outfit", "environment", "style", "composition"]
    license = "Apache-2.0"
    description = "Видео 24 кадра/с. Начальный кадр задаёт персонажа и сцену; движение и камера — промптом."
    limits = [
        "Конечный кадр модель не поддерживает (нужна Wan 2.2 14B FLF2V).",
        "Референсы персонажа, окружения и стиля напрямую не принимаются: сначала Klein 4B строит по ним ключевой кадр, затем Wan анимирует его (кадр сохраняется в результатах).",
        "Замеры на Quadro RTX 3000, 2 с видео: черновик ≈2–5 мин, стандарт 832×480 ≈13 мин; 720p 5 с — около часа.",
        "В черновом разрешении персонажи плывут и теряют сходство — черновик годится для проверки движения камеры и сцены; для персонажей используйте «Стандарт».",
        "Text-to-video у этой модели слабый: надёжнее сделать кадр в Klein и анимировать его.",
    ]
    defaults = {"steps": 20}
    video_options = {
        "durations": [2, 3, 4, 5],
        "default_duration": 3,
        "resolutions": {k: v[0] for k, v in RESOLUTIONS.items()},
        "default_resolution": "sd",
        "aspects": ["16:9", "9:16", "1:1", "4:3", "3:4"],
        "cameras": CAMERAS,
        "time_note": "2 с в стандартном разрешении ≈ 13 мин; время растёт пропорционально длительности и разрешению.",
    }

    def __init__(self):
        self.klein = Klein4B()

    def validate(self, p):
        err = super().validate(p)
        if err:
            return err
        if sum(r["role"] == "start" for r in p["refs"]) > 1:
            return "Начальный кадр может быть только один"
        if p["mode"] == "i2v" and not p["refs"]:
            return "Для режима «Изображение → видео» прикрепите начальный кадр"
        has_start = any(r["role"] == "start" for r in p["refs"])
        if p["mode"] == "t2v" and has_start:
            return "Начальный кадр используется в режиме «Изображение → видео»"
        if has_start and len(p["refs"]) > 1:
            return "Вместе с начальным кадром другие референсы не используются: персонаж и сцена берутся из кадра. Уберите их или уберите начальный кадр — тогда ключевой кадр будет построен по референсам."
        if any(r["role"] != "start" for r in p["refs"]) and self.klein.missing_files():
            return "Для референсов персонажа/стиля нужна модель Klein 4B для ключевого кадра"
        return None

    def _size(self, p, start):
        mp = RESOLUTIONS.get(p.get("resolution") or "sd", RESOLUTIONS["sd"])[1]
        if start:
            return size_like(start["width"], start["height"], mp, multiple=32)
        return size_for(p.get("aspect") or "16:9", mp, multiple=32)

    def keyframe(self, p, refs, index):
        """Граф ключевого кадра Klein, если есть референсы без начального кадра; иначе None."""
        if any(r["role"] == "start" for r in refs) or not refs:
            return None
        kp = {"mode": "t2i", "prompt": p["prompt"], "aspect": p.get("aspect") or "16:9", "megapixels": 1.0,
              "seed": p["seed"], "role_prompts": p.get("role_prompts", True), "ref_megapixels": p.get("ref_megapixels")}
        graph, meta = self.klein.build(kp, refs, index)
        graph["save"]["inputs"]["filename_prefix"] = "keyframe"
        return graph, meta

    def build(self, p, refs, index):
        start = next((r for r in refs if r["role"] == "start"), None)
        w, h = self._size(p, start)
        length = round(float(p.get("duration") or 3) * FPS / 4) * 4 + 1
        seed = int(p["seed"]) + index
        prompt = p["prompt"]
        if p.get("camera") in CAMERA_PROMPTS:
            prompt = f"{prompt}\n{CAMERA_PROMPTS[p['camera']]}"

        g = {
            "unet": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "Wan2.2-TI2V-5B-Q4_K_M.gguf"}},
            "msd": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["unet", 0], "shift": 8.0}},
            "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
            "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
            "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
            "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": p.get("negative") or NEGATIVE}},
            "lat": {"class_type": "Wan22ImageToVideoLatent", "inputs": {"vae": ["vae", 0], "width": w, "height": h, "length": length, "batch_size": 1}},
            "samp": {"class_type": "KSampler", "inputs": {"model": ["msd", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["lat", 0],
                                                          "seed": seed, "steps": int(p.get("steps") or 20), "cfg": 5.0,
                                                          "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1.0}},
            "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["samp", 0], "vae": ["vae", 0]}},
            "video": {"class_type": "CreateVideo", "inputs": {"images": ["dec", 0], "fps": float(FPS)}},
            "save": {"class_type": "SaveVideo", "inputs": {"video": ["video", 0], "filename_prefix": "studio", "format": "mp4"}},
        }
        if start:
            g["start"] = {"class_type": "LoadImage", "inputs": {"image": start["file"]}}
            g["lat"]["inputs"]["start_image"] = ["start", 0]
        return g, {"width": w, "height": h, "seed": seed, "prompt_sent": prompt, "frames": length, "fps": FPS}
