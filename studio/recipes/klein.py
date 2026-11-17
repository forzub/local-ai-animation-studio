"""FLUX.2 Klein 4B distilled: text-to-image, редактирование, img2img, до нескольких референсов.

Референсы передаются штатным для FLUX.2 механизмом ReferenceLatent (латенты изображений
добавляются в контекст DiT); на роли модель ссылается в промпте как "image N".
"""
from .base import Recipe, size_for, size_like, role_prompt


class Klein4B(Recipe):
    id = "flux2-klein-4b"
    name = "FLUX.2 Klein 4B"
    kind = "image"
    modes = {"t2i": "Текст → изображение", "edit": "Редактирование", "i2i": "Вариация изображения"}
    files = ["diffusion_models/flux-2-klein-4b-fp8.safetensors", "text_encoders/qwen_3_4b.safetensors", "vae/flux2-vae.safetensors"]
    max_refs = 6
    ref_roles = ["base", "character", "outfit", "environment", "style", "composition"]
    license = "Apache-2.0"
    description = "Быстрая модель (≈45 с на 1 Мп). Нативно принимает несколько референсов и понимает инструкции по редактированию."
    limits = [
        "Роли референсов передаются модели текстовой инструкцией «image N …» — так модель обучена; отдельного ControlNet для позы нет, поэтому «Композиция / поза» соблюдается приблизительно.",
        "Каждый референс заметно замедляет генерацию (2 референса ≈ 3,5 мин на 1 Мп).",
    ]
    defaults = {"steps": 4, "megapixels": 1.0, "aspect": "1:1", "strength": 0.6}
    unet_file = "flux-2-klein-4b-fp8.safetensors"
    clip_file = "qwen_3_4b.safetensors"

    def validate(self, p):
        err = super().validate(p)
        if err:
            return err
        if p["mode"] in ("edit", "i2i") and not p["refs"]:
            return "Для редактирования и вариаций нужно прикрепить исходное изображение"
        return None

    def build(self, p, refs, index):
        mode = p["mode"]
        mp = float(p.get("megapixels") or 1.0)
        steps = int(p.get("steps") or 4)
        seed = int(p["seed"]) + index

        # Исходник для edit/i2i: явная роль base, иначе первый референс. Он идёт первым ("image 1").
        if mode in ("edit", "i2i"):
            base_i = next((i for i, r in enumerate(refs) if r["role"] == "base"), 0)
            refs = [dict(refs[base_i], role="base")] + [r for i, r in enumerate(refs) if i != base_i]
            w, h = size_like(refs[0]["width"], refs[0]["height"], mp)
        else:
            w, h = size_for(p.get("aspect") or "1:1", mp)

        # В i2i исходник задаёт только стартовый латент: как ReferenceLatent он «приклеивает» результат к оригиналу.
        init_image = refs[0]["file"] if mode == "i2i" else None
        if mode == "i2i":
            refs = refs[1:]

        prompt = p["prompt"]
        if refs and p.get("role_prompts", True):
            prompt = role_prompt(refs, prompt)

        ref_mp = float(p.get("ref_megapixels") or (1.0 if len(refs) <= 2 else 0.6))
        g = {
            "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": self.unet_file, "weight_dtype": "default"}},
            "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": self.clip_file, "type": "flux2", "device": "default"}},
            "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
            "pos": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt}},
            "neg": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["pos", 0]}},
            "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
            "sel": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
            "dec": {"class_type": "VAEDecode", "inputs": {"samples": ["samp", 0], "vae": ["vae", 0]}},
            "save": {"class_type": "SaveImage", "inputs": {"images": ["dec", 0], "filename_prefix": "studio"}},
        }
        pos, neg = ["pos", 0], ["neg", 0]
        for i, r in enumerate(refs):
            g[f"ref{i}"] = {"class_type": "LoadImage", "inputs": {"image": r["file"]}}
            g[f"refs{i}"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": [f"ref{i}", 0], "upscale_method": "lanczos", "megapixels": ref_mp, "resolution_steps": 16}}
            g[f"refe{i}"] = {"class_type": "VAEEncode", "inputs": {"pixels": [f"refs{i}", 0], "vae": ["vae", 0]}}
            g[f"refp{i}"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": pos, "latent": [f"refe{i}", 0]}}
            g[f"refn{i}"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": neg, "latent": [f"refe{i}", 0]}}
            pos, neg = [f"refp{i}", 0], [f"refn{i}", 0]
        g["guid"] = {"class_type": "CFGGuider", "inputs": {"model": ["unet", 0], "positive": pos, "negative": neg, "cfg": 1.0}}

        if mode == "i2i":
            strength = min(1.0, max(0.05, float(p.get("strength") or 0.6)))
            total = max(steps, round(steps / strength))
            g["sch"] = {"class_type": "Flux2Scheduler", "inputs": {"steps": total, "width": w, "height": h}}
            g["split"] = {"class_type": "SplitSigmas", "inputs": {"sigmas": ["sch", 0], "step": total - steps}}
            g["initl"] = {"class_type": "LoadImage", "inputs": {"image": init_image}}
            g["init"] = {"class_type": "ImageScale", "inputs": {"image": ["initl", 0], "upscale_method": "lanczos", "width": w, "height": h, "crop": "center"}}
            g["lat"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["init", 0], "vae": ["vae", 0]}}
            sigmas = ["split", 1]
        else:
            g["sch"] = {"class_type": "Flux2Scheduler", "inputs": {"steps": steps, "width": w, "height": h}}
            g["lat"] = {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
            sigmas = ["sch", 0]
        g["samp"] = {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["noise", 0], "guider": ["guid", 0], "sampler": ["sel", 0], "sigmas": sigmas, "latent_image": ["lat", 0]}}
        return g, {"width": w, "height": h, "seed": seed, "prompt_sent": prompt}


class Klein9B(Klein4B):
    id = "flux2-klein-9b"
    name = "FLUX.2 Klein 9B"
    files = ["diffusion_models/flux-2-klein-9b-fp8.safetensors", "text_encoders/qwen_3_8b_fp8mixed.safetensors", "vae/flux2-vae.safetensors"]
    license = "FLUX Non-Commercial License (только некоммерческое использование)"
    description = ("Старшая версия Klein: те же режимы и до 6 референсов, но заметно лучше детализация, анатомия и следование промпту. "
                   "Медленнее 4B — модель и энкодер не помещаются в 6 ГБ целиком.")
    limits = [
        "Роли референсов передаются текстовой инструкцией «image N …»; «Композиция / поза» соблюдается приблизительно.",
        "Замер на Quadro RTX 3000 (1 Мп): по тексту ≈ 2,5 мин, правка с 2 референсами ≈ 9 мин.",
        "Иногда дорисовывает в углу псевдо-подпись или логотип — помогает «no text, no watermark» в промпте.",
    ]
    unet_file = "flux-2-klein-9b-fp8.safetensors"
    clip_file = "qwen_3_8b_fp8mixed.safetensors"
