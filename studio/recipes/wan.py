"""Видеомодели Wan 2.2.

- TI2V-5B (GGUF Q4_K_M): text-to-video и image-to-video, 24 кадра/с.
- I2V-A14B (GGUF Q4_K_M, high+low noise) + lightx2v 4-step LoRA: image-to-video и
  начальный+конечный кадр, 16 кадров/с.

Референсы персонажа/окружения/стиля Wan напрямую не принимает. Если они прикреплены без
начального кадра, задача выполняется в два этапа: Klein 4B строит ключевой кадр, Wan его оживляет.
"""
from .base import Recipe
from .klein import Klein4B

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
# Пресет -> номинальная короткая сторона кадра.
SHORT_SIDE = {"draft": 360, "sd": 480, "hd": 720}
ASPECT_RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4}


def video_size(ratio, short, multiple):
    """Размер кадра по соотношению сторон и короткой стороне; 16:9 @720 -> 1280×720 (кратн. 16) или 1280×704 (кратн. 32)."""
    w, h = (short * ratio, short) if ratio >= 1 else (short, short / ratio)
    snap = lambda v: max(multiple, int(round(v / multiple - 1e-6)) * multiple)
    return snap(w), snap(h)


class WanBase(Recipe):
    uses_negative = True
    kind = "video"
    max_refs = 6
    license = "Apache-2.0"
    fps = 16
    size_multiple = 16
    end_frame = False
    keyframe_from_prompt = False  # строить ключевой кадр, даже если референсов нет

    def __init__(self):
        self.klein = Klein4B()

    def video_opts(self, resolutions, default, time_note):
        return {
            "durations": [2, 3, 4, 5],
            "default_duration": 3,
            "resolutions": resolutions,
            "default_resolution": default,
            "aspects": list(ASPECT_RATIOS),
            "cameras": CAMERAS,
            "time_note": time_note,
            "end_frame": self.end_frame,
        }

    def validate(self, p):
        err = super().validate(p)
        if err:
            return err
        refs = p["refs"]
        n_start = sum(r["role"] == "start" for r in refs)
        n_end = sum(r["role"] == "end" for r in refs)
        if n_start > 1 or n_end > 1:
            return "Начальный и конечный кадр могут быть только в одном экземпляре"
        if p["mode"] == "t2v" and (n_start or n_end):
            return "Начальный/конечный кадр используются в режимах с изображением"
        if p["mode"] in ("i2v", "flf") and not n_start and not refs and not self.keyframe_from_prompt:
            return "Прикрепите начальный кадр или референсы для ключевого кадра"
        if not n_start and not p["prompt"]:
            return "Введите промпт: по нему будет построен ключевой кадр"
        if p["mode"] == "flf" and not n_end:
            return "Для режима «Начальный + конечный кадр» прикрепите конечный кадр"
        if n_end and p["mode"] != "flf":
            return "Конечный кадр используется только в режиме «Начальный + конечный кадр»"
        other = [r for r in refs if r["role"] not in ("start", "end")]
        if n_start and other:
            return ("Вместе с начальным кадром другие референсы не используются: персонаж и сцена берутся из кадра. "
                    "Уберите их или уберите начальный кадр — тогда ключевой кадр будет построен по референсам.")
        if other and self.klein.missing_files():
            return "Для референсов персонажа/стиля нужна модель Klein 4B для ключевого кадра"
        return None

    def keyframe(self, p, refs, index):
        """Граф ключевого кадра Klein, если есть референсы, но нет начального кадра; иначе None."""
        other = [r for r in refs if r["role"] not in ("start", "end")]
        if any(r["role"] == "start" for r in refs) or (not other and not self.keyframe_from_prompt):
            return None
        kp = {"mode": "t2i", "prompt": p["prompt"], "aspect": p.get("aspect") or "16:9", "megapixels": 1.0,
              "seed": p["seed"], "role_prompts": p.get("role_prompts", True), "ref_megapixels": p.get("ref_megapixels")}
        graph, meta = self.klein.build(kp, other, index)
        graph["save"]["inputs"]["filename_prefix"] = "keyframe"
        return graph, meta

    def frame_size(self, p, start):
        short = SHORT_SIDE.get(p.get("resolution") or self.video_options["default_resolution"], 480)
        ratio = start["width"] / start["height"] if start else ASPECT_RATIOS.get(p.get("aspect") or "16:9", 16 / 9)
        return video_size(ratio, short, self.size_multiple)

    def common(self, p, index):
        prompt = p["prompt"]
        if p.get("camera") in CAMERA_PROMPTS:
            prompt = f"{prompt}\n{CAMERA_PROMPTS[p['camera']]}"
        length = round(float(p.get("duration") or 3) * self.fps / 4) * 4 + 1
        return prompt, length, int(p["seed"]) + index

    def save_nodes(self, images):
        return {
            "video": {"class_type": "CreateVideo", "inputs": {"images": images, "fps": float(self.fps)}},
            "save": {"class_type": "SaveVideo", "inputs": {"video": ["video", 0], "filename_prefix": "studio", "format": "mp4"}},
        }


class WanTI2V5B(WanBase):
    id = "wan2.2-ti2v-5b"
    name = "Wan 2.2 TI2V 5B (Q4)"
    modes = {"t2v": "Текст → видео", "i2v": "Изображение → видео"}
    files = ["unet/Wan2.2-TI2V-5B-Q4_K_M.gguf", "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "vae/wan2.2_vae.safetensors"]
    ref_roles = ["start", "character", "outfit", "environment", "style", "composition"]
    fps = 24
    size_multiple = 32
    description = "Лёгкая видеомодель, 24 кадра/с, единственная с text-to-video. Начальный кадр задаёт персонажа и сцену."
    limits = [
        "Конечный кадр не поддерживается — используйте Wan 2.2 I2V 14B.",
        "Референсы персонажа, окружения и стиля: сначала Klein 4B строит по ним ключевой кадр, затем Wan анимирует его.",
        "Замеры на Quadro RTX 3000, 2 с видео: черновик ≈2–5 мин, 480p ≈13 мин; 720p (1280×704) 5 с — около часа.",
        "В черновом разрешении персонажи плывут и теряют сходство.",
        "Text-to-video слабый: надёжнее сделать кадр в Klein и анимировать его.",
    ]
    defaults = {"steps": 20}

    def __init__(self):
        super().__init__()
        self.video_options = self.video_opts(
            {"draft": "Черновик · 640×352", "sd": "480p · 864×480", "hd": "720p · 1280×704 (родное, очень долго)"},
            "hd", "720p — родное разрешение модели; 5 с в 720p на 6 ГБ — около часа.")

    def build(self, p, refs, index):
        start = next((r for r in refs if r["role"] == "start"), None)
        w, h = self.frame_size(p, start)
        prompt, length, seed = self.common(p, index)
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
            **self.save_nodes(["dec", 0]),
        }
        if start:
            g["start"] = {"class_type": "LoadImage", "inputs": {"image": start["file"]}}
            g["lat"]["inputs"]["start_image"] = ["start", 0]
        return g, {"width": w, "height": h, "seed": seed, "prompt_sent": prompt, "frames": length, "fps": self.fps}


class WanI2V14B(WanBase):
    id = "wan2.2-i2v-14b"
    name = "Wan 2.2 I2V 14B (Q4, 4 шага)"
    modes = {"i2v": "Изображение → видео", "flf": "Начальный + конечный кадр"}
    files = ["unet/Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf", "unet/Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf",
             "loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
             "loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
             "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "vae/wan_2.1_vae.safetensors"]
    ref_roles = ["start", "end", "character", "outfit", "environment", "style", "composition"]
    fps = 16
    size_multiple = 16
    end_frame = True
    keyframe_from_prompt = True
    heavy = True
    description = ("Качественная модель image-to-video (две экспертные модели high/low noise) с ускорением lightx2v до 4 шагов. "
                   "Умеет переход от начального к конечному кадру.")
    limits = [
        "Text-to-video нет: без начального кадра он строится в Klein 4B по промпту и референсам.",
        "16 кадров/с (родная частота модели).",
        "Замеры на Quadro RTX 3000, 2 с видео: 480p ≈ 12 мин, 720p (1280×720) ≈ 50 мин. Время растёт примерно пропорционально длительности.",
        "Шаги больше 4 с LoRA lightx2v не улучшают результат; CFG фиксирован = 1.",
    ]
    defaults = {"steps": 4}

    def __init__(self):
        super().__init__()
        self.video_options = self.video_opts(
            {"draft": "Черновик · 640×352", "sd": "480p · 848×480 (родное)", "hd": "720p · 1280×720"},
            "hd", "2 с: 480p ≈ 12 мин, 720p ≈ 50 мин. Удобно подобрать движение на 480p с тем же seed, затем сделать финал в 720p.")

    def build(self, p, refs, index):
        start = next((r for r in refs if r["role"] == "start"), None)
        end = next((r for r in refs if r["role"] == "end"), None)
        w, h = self.frame_size(p, start or end)
        prompt, length, seed = self.common(p, index)
        steps = int(p.get("steps") or 4)
        switch = max(1, steps // 2)
        g = {
            "unet_hi": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf"}},
            "unet_lo": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf"}},
            "lora_hi": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["unet_hi", 0], "lora_name": "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", "strength_model": 1.0}},
            "lora_lo": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["unet_lo", 0], "lora_name": "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors", "strength_model": 1.0}},
            "msd_hi": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["lora_hi", 0], "shift": 5.0}},
            "msd_lo": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["lora_lo", 0], "shift": 5.0}},
            "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
            "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
            "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
            "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": p.get("negative") or NEGATIVE}},
            "start": {"class_type": "LoadImage", "inputs": {"image": start["file"]}},
        }
        cond = {"positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0],
                "width": w, "height": h, "length": length, "batch_size": 1, "start_image": ["start", 0]}
        if end:
            g["end"] = {"class_type": "LoadImage", "inputs": {"image": end["file"]}}
            g["i2v"] = {"class_type": "WanFirstLastFrameToVideo", "inputs": {**cond, "end_image": ["end", 0]}}
        else:
            g["i2v"] = {"class_type": "WanImageToVideo", "inputs": cond}
        sampler = {"cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "steps": steps,
                   "positive": ["i2v", 0], "negative": ["i2v", 1], "noise_seed": seed}
        g["samp_hi"] = {"class_type": "KSamplerAdvanced", "inputs": {**sampler, "model": ["msd_hi", 0], "latent_image": ["i2v", 2],
                                                                     "add_noise": "enable", "start_at_step": 0, "end_at_step": switch,
                                                                     "return_with_leftover_noise": "enable"}}
        g["samp_lo"] = {"class_type": "KSamplerAdvanced", "inputs": {**sampler, "model": ["msd_lo", 0], "latent_image": ["samp_hi", 0],
                                                                     "add_noise": "disable", "start_at_step": switch, "end_at_step": 10000,
                                                                     "return_with_leftover_noise": "disable"}}
        g["dec"] = {"class_type": "VAEDecode", "inputs": {"samples": ["samp_lo", 0], "vae": ["vae", 0]}}
        g.update(self.save_nodes(["dec", 0]))
        return g, {"width": w, "height": h, "seed": seed, "prompt_sent": prompt, "frames": length, "fps": self.fps}
