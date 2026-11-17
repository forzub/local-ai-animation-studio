"""Дополнительные модели изображений: Qwen-Image 2.1, Qwen-Image-Edit 2509, Z-Image Turbo, Chroma1-HD.

Референсы везде передаются штатным механизмом модели:
- Qwen-Image 2.1 и Qwen-Edit 2509 — изображения видит VL-энкодер, а их латенты добавляются в контекст DiT
  (reference_latents), на референсы модель ссылается в промпте;
- Z-Image и Chroma референсов не принимают — у них есть только честный img2img: исходник задаёт
  стартовый латент, «сила» — какая доля шагов пересчитывается.
"""
from .base import Recipe, size_for, size_like, role_prompt

# 8 сигм дистиллированной Turbo-версии из официального шаблона Comfy-Org (image_qwen_image_2_1_turbo_*)
QWEN21_TURBO_SIGMAS = "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0"

CHROMA_NEGATIVE = ("This low quality greyscale unfinished sketch is inaccurate and flawed. The image is very blurred "
                   "and lacks detail with excessive chromatic aberrations and blurred text.")


def _order_refs(p, refs):
    """В edit исходник (роль base или первый референс) идёт первым — от него берётся размер результата."""
    if p["mode"] != "edit":
        return refs
    base_i = next((i for i, r in enumerate(refs) if r["role"] == "base"), 0)
    return [dict(refs[base_i], role="base")] + [r for i, r in enumerate(refs) if i != base_i]


def _need_ref(p, modes=("edit", "i2i")):
    if p["mode"] in modes and not p["refs"]:
        return "Для этого режима нужно прикрепить исходное изображение"
    return None


class QwenImage21(Recipe):
    id = "qwen-image-2.1"
    name = "Qwen-Image 2.1 Turbo"
    kind = "image"
    modes = {"t2i": "Текст → изображение", "edit": "Редактирование"}
    files = ["diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors",
             "text_encoders/qwen3vl_8b_int8_convrot.safetensors", "vae/qwen_image_2.1_vae_bf16.safetensors"]
    max_refs = 4
    ref_roles = ["base", "character", "outfit", "environment", "style", "composition"]
    license = "Apache-2.0"
    description = ("Сильная модель Alibaba (7B, сентябрь 2026): и генерация по тексту, и правка по инструкции "
                   "с несколькими референсами (персонаж, одежда, окружение, стиль). Хорошо понимает длинные промпты и пишет текст на картинке.")
    limits = [
        "Турбо-версия: фиксированные 8 шагов, поле «Шаги» не используется. Замер: ≈ 2,5 мин по тексту, ≈ 6 мин правка с 2 референсами (1 Мп).",
        "Референсы модель видит целиком и сама решает, что из них взять; роль подсказывается текстом «<imageN> …».",
        "В режиме редактирования размер результата берётся с исходника (image 1).",
    ]
    defaults = {"steps": 8, "megapixels": 1.0, "aspect": "1:1"}

    def validate(self, p):
        return super().validate(p) or _need_ref(p, ("edit",))

    def build(self, p, refs, index):
        mp = float(p.get("megapixels") or 1.0)
        seed = int(p["seed"]) + index
        refs = _order_refs(p, refs)
        prompt = p["prompt"]
        if refs and p.get("role_prompts", True):
            prompt = role_prompt(refs, prompt, tag="<image{n}>")
        # resolution — бюджет пикселей для референсов (сторона квадрата той же площади), кратно 32
        res = max(256, round((mp ** 0.5) * 1024 / 32) * 32)
        enc = {"clip": ["clip", 0], "prompt": prompt, "negative_prompt": "", "resolution": res}
        g = {
            "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_turbo_int8_convrot.safetensors", "weight_dtype": "default"}},
            "cache": {"class_type": "QwenImage21Cache", "inputs": {"model": ["unet", 0], "device": "auto", "dtype": "default"}},
            "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
            "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
            "enc": {"class_type": "TextEncodeQwenImage21", "inputs": enc},
            "guid": {"class_type": "CFGGuider", "inputs": {"model": ["cache", 0], "positive": ["enc", 0], "negative": ["enc", 1], "cfg": 1.0}},
            "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
            "sel": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
            "sig": {"class_type": "ManualSigmas", "inputs": {"sigmas": QWEN21_TURBO_SIGMAS}},
            "samp": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["noise", 0], "guider": ["guid", 0], "sampler": ["sel", 0], "sigmas": ["sig", 0], "latent_image": None}},
            "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["samp", 0], "vae": ["vae", 0]}},
            "save": {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": "studio"}},
        }
        if refs:
            enc["vae"] = ["vae", 0]
            for i, r in enumerate(refs):
                g[f"ref{i}"] = {"class_type": "LoadImage", "inputs": {"image": r["file"]}}
                enc[f"images.image_{i + 1}"] = [f"ref{i}", 0]
        if p["mode"] == "edit":
            # латент кодировщика — точно под размер исходника; другой размер сдвигает правку
            r0 = refs[0]
            scale = (res * res / (r0["width"] * r0["height"])) ** 0.5
            w, h = max(32, round(r0["width"] * scale / 32) * 32), max(32, round(r0["height"] * scale / 32) * 32)
            g["samp"]["inputs"]["latent_image"] = ["enc", 2]
        else:
            w, h = size_for(p.get("aspect") or "1:1", mp, 32)
            g["lat"] = {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
            g["samp"]["inputs"]["latent_image"] = ["lat", 0]
        return g, {"width": w, "height": h, "seed": seed, "prompt_sent": prompt}


class QwenEdit2509(Recipe):
    id = "qwen-image-edit-2509"
    name = "Qwen-Image-Edit 2509 (20B, 4 шага)"
    kind = "image"
    modes = {"edit": "Редактирование", "t2i": "Текст → изображение"}
    files = ["diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors",
             "loras/Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors",
             "text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors", "vae/qwen_image_vae.safetensors"]
    max_refs = 3
    ref_roles = ["base", "character", "outfit", "environment", "style", "composition"]
    license = "Apache-2.0"
    description = ("Крупная модель правки по инструкции (20B) с ускоряющей LoRA на 4 шага. Хорошо сохраняет лицо и детали исходника, "
                   "переносит персонажа/одежду/фон между 2–3 картинками.")
    limits = [
        "Модель весит 20 ГБ и на 6 ГБ подгружается из оперативной памяти: замер на Quadro RTX 3000 — ≈ 90 мин на картинку 1 Мп с 2 референсами. Для тех же задач обычно лучше Qwen-Image 2.1 (≈ 6 мин).",
        "Не больше 3 референсов. Генерация по тексту без референсов возможна, но модель обучалась прежде всего на правке.",
    ]
    defaults = {"steps": 4, "megapixels": 1.0, "aspect": "1:1"}
    heavy = True

    def validate(self, p):
        return super().validate(p) or _need_ref(p, ("edit",))

    def build(self, p, refs, index):
        mp = float(p.get("megapixels") or 1.0)
        steps = int(p.get("steps") or 4)
        seed = int(p["seed"]) + index
        refs = _order_refs(p, refs)
        prompt = p["prompt"]
        if refs and p.get("role_prompts", True):
            prompt = role_prompt(refs, prompt)
        g = {
            "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_edit_2509_fp8_e4m3fn.safetensors", "weight_dtype": "default"}},
            "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["unet", 0], "lora_name": "Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors", "strength_model": 1.0}},
            "msamp": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["lora", 0], "shift": 3.0}},
            "norm": {"class_type": "CFGNorm", "inputs": {"model": ["msamp", 0], "strength": 1.0}},
            "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
            "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
            "pos": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["clip", 0], "prompt": prompt, "vae": ["vae", 0]}},
            "neg": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["clip", 0], "prompt": "", "vae": ["vae", 0]}},
            "ks": {"class_type": "KSampler", "inputs": {"model": ["norm", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": None,
                                                       "seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
            "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["vae", 0]}},
            "save": {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": "studio"}},
        }
        for i, r in enumerate(refs):
            g[f"ref{i}"] = {"class_type": "LoadImage", "inputs": {"image": r["file"]}}
            g["pos"]["inputs"][f"image{i + 1}"] = [f"ref{i}", 0]
            g["neg"]["inputs"][f"image{i + 1}"] = [f"ref{i}", 0]
        if p["mode"] == "edit":
            w, h = size_like(refs[0]["width"], refs[0]["height"], mp, 16)
            g["base"] = {"class_type": "ImageScale", "inputs": {"image": ["ref0", 0], "upscale_method": "lanczos", "width": w, "height": h, "crop": "center"}}
            g["lat"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["base", 0], "vae": ["vae", 0]}}
        else:
            w, h = size_for(p.get("aspect") or "1:1", mp, 16)
            g["lat"] = {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
        g["ks"]["inputs"]["latent_image"] = ["lat", 0]
        return g, {"width": w, "height": h, "seed": seed, "prompt_sent": prompt}


class _Img2ImgRecipe(Recipe):
    """Модели без механизма референсов: текст → изображение и img2img от исходника."""
    kind = "image"
    modes = {"t2i": "Текст → изображение", "i2i": "Вариация изображения"}
    max_refs = 1
    ref_roles = ["base"]

    def validate(self, p):
        err = super().validate(p) or _need_ref(p, ("i2i",))
        if not err and p["mode"] == "t2i" and p["refs"]:
            err = f"{self.name} не принимает референсы при генерации по тексту — используйте режим «Вариация изображения»"
        return err

    def latent(self, g, p, refs, mp, multiple):
        """Пустой латент или закодированный исходник; возвращает (w, h, denoise)."""
        if p["mode"] == "i2i":
            w, h = size_like(refs[0]["width"], refs[0]["height"], mp, multiple)
            g["initl"] = {"class_type": "LoadImage", "inputs": {"image": refs[0]["file"]}}
            g["init"] = {"class_type": "ImageScale", "inputs": {"image": ["initl", 0], "upscale_method": "lanczos", "width": w, "height": h, "crop": "center"}}
            g["lat"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["init", 0], "vae": ["vae", 0]}}
            return w, h, min(1.0, max(0.05, float(p.get("strength") or 0.6)))
        w, h = size_for(p.get("aspect") or "1:1", mp, multiple)
        g["lat"] = {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
        return w, h, 1.0


class ZImageTurbo(_Img2ImgRecipe):
    id = "z-image-turbo"
    name = "Z-Image Turbo"
    files = ["diffusion_models/z_image_turbo_int8_convrot.safetensors", "text_encoders/qwen_3_4b.safetensors", "vae/ae.safetensors"]
    license = "Apache-2.0"
    description = "Быстрая фотореалистичная модель Alibaba (6B, 8 шагов): детальная генерация по тексту, хорошо пишет текст на картинке."
    limits = [
        "Референсов не принимает: можно только взять картинку за основу (вариация), «Сила» задаёт, насколько сильно её менять.",
        "Дистиллирована под 8 шагов без негативного промпта — больше шагов почти не улучшают результат.",
    ]
    defaults = {"steps": 8, "megapixels": 1.0, "aspect": "1:1", "strength": 0.6}

    def build(self, p, refs, index):
        mp = float(p.get("megapixels") or 1.0)
        seed = int(p["seed"]) + index
        g = {
            "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image_turbo_int8_convrot.safetensors", "weight_dtype": "default"}},
            "msamp": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["unet", 0], "shift": 3.0}},
            "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"}},
            "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
            "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": p["prompt"]}},
            "neg": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["pos", 0]}},
            "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["vae", 0]}},
            "save": {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": "studio"}},
        }
        w, h, denoise = self.latent(g, p, refs, mp, 16)
        g["ks"] = {"class_type": "KSampler", "inputs": {"model": ["msamp", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["lat", 0],
                                                      "seed": seed, "steps": int(p.get("steps") or 8), "cfg": 1.0,
                                                      "sampler_name": "res_multistep", "scheduler": "simple", "denoise": denoise}}
        return g, {"width": w, "height": h, "seed": seed, "prompt_sent": p["prompt"]}


class Chroma1HD(_Img2ImgRecipe):
    id = "chroma1-hd"
    name = "Chroma1-HD (8.9B)"
    files = ["diffusion_models/Chroma1-HD-fp8mixed-final.safetensors", "text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors", "vae/ae.safetensors"]
    license = "Apache-2.0"
    description = ("Нецензурированная художественная модель на основе FLUX.1-schnell: широкий диапазон стилей, понимает негативный промпт. "
                   "Медленная — полноценные 26 шагов с CFG.")
    limits = [
        "Референсов не принимает: можно только взять картинку за основу (вариация).",
        "Каждый шаг считается дважды (CFG): замер ≈ 14 мин на картинку 1 Мп, 26 шагов.",
    ]
    defaults = {"steps": 26, "megapixels": 1.0, "aspect": "1:1", "strength": 0.6}
    uses_negative = True

    def build(self, p, refs, index):
        mp = float(p.get("megapixels") or 1.0)
        seed = int(p["seed"]) + index
        g = {
            "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "Chroma1-HD-fp8mixed-final.safetensors", "weight_dtype": "default"}},
            "msamp": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["unet", 0], "shift": 1.0}},
            "clipl": {"class_type": "CLIPLoader", "inputs": {"clip_name": "t5xxl_fp8_e4m3fn_scaled.safetensors", "type": "chroma", "device": "default"}},
            "clip": {"class_type": "T5TokenizerOptions", "inputs": {"clip": ["clipl", 0], "min_padding": 0, "min_length": 0}},
            "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
            "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": p["prompt"]}},
            "neg": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": p.get("negative") or CHROMA_NEGATIVE}},
            "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["ks", 0], "vae": ["vae", 0]}},
            "save": {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": "studio"}},
        }
        w, h, denoise = self.latent(g, p, refs, mp, 16)
        g["ks"] = {"class_type": "KSampler", "inputs": {"model": ["msamp", 0], "positive": ["pos", 0], "negative": ["neg", 0], "latent_image": ["lat", 0],
                                                      "seed": seed, "steps": int(p.get("steps") or 26), "cfg": 3.5,
                                                      "sampler_name": "euler", "scheduler": "beta", "denoise": denoise}}
        return g, {"width": w, "height": h, "seed": seed, "prompt_sent": p["prompt"]}
