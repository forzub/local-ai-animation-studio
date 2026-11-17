"""Общая часть рецептов: описание модели, роли референсов, расчёт размеров."""
from .. import config

ROLES = {
    "base": "Исходник для редактирования",
    "start": "Начальный кадр",
    "end": "Конечный кадр",
    "character": "Персонаж",
    "outfit": "Внешность / одежда",
    "environment": "Окружение",
    "style": "Художественный стиль",
    "composition": "Композиция / поза",
}

# Как роль объясняется модели, которая ссылается на референсы как "image N".
ROLE_INSTRUCTIONS = {
    "base": "Image {n} is the image to edit: keep its composition, framing and everything that is not asked to change.",
    "character": "Image {n} shows the character: keep exactly the same face, identity, hairstyle and body proportions.",
    "outfit": "Use the clothing, accessories and appearance details from image {n}.",
    "environment": "Use the location and environment from image {n} as the setting.",
    "style": "Render in the art style of image {n}: same linework, color palette, shading and rendering technique, but not its content.",
    "composition": "Follow the composition, pose and camera framing of image {n}.",
}

ASPECTS = ["1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "21:9"]


def size_for(aspect, megapixels, multiple=16):
    a, b = (float(x) for x in aspect.split(":"))
    px = megapixels * 1024 * 1024
    h = (px * b / a) ** 0.5
    w = h * a / b
    return max(multiple, round(w / multiple) * multiple), max(multiple, round(h / multiple) * multiple)


def size_like(width, height, megapixels, multiple=16):
    scale = (megapixels * 1024 * 1024 / (width * height)) ** 0.5
    return max(multiple, round(width * scale / multiple) * multiple), max(multiple, round(height * scale / multiple) * multiple)


def role_prompt(refs, prompt):
    lines = [ROLE_INSTRUCTIONS[r["role"]].format(n=i + 1) for i, r in enumerate(refs) if r["role"] in ROLE_INSTRUCTIONS]
    return "\n".join(lines + [prompt]) if lines else prompt


class Recipe:
    id = ""
    name = ""
    kind = "image"  # image | video
    modes = {}  # mode -> подпись
    files = []  # файлы относительно vendor/ComfyUI/models
    max_refs = 0
    ref_roles = []
    license = ""
    description = ""
    limits = []  # честные ограничения, показываются в интерфейсе
    defaults = {}
    video_options = None

    def missing_files(self):
        return [f for f in self.files if not (config.COMFY_MODELS / f).exists()]

    def info(self):
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "modes": self.modes,
            "max_refs": self.max_refs, "ref_roles": self.ref_roles, "license": self.license,
            "description": self.description, "limits": self.limits, "defaults": self.defaults,
            "video_options": self.video_options,
            "missing": self.missing_files(),
        }

    def validate(self, p):
        """Вернуть текст ошибки или None."""
        if p["mode"] not in self.modes:
            return f"Модель {self.name} не поддерживает режим {p['mode']}"
        if len(p["refs"]) > self.max_refs:
            return f"Модель {self.name} принимает не более {self.max_refs} референсов"
        for r in p["refs"]:
            if r["role"] not in self.ref_roles:
                return f"Модель {self.name} не умеет использовать роль «{ROLES.get(r['role'], r['role'])}»"
        return None

    def build(self, p, refs, index):
        """Собрать API-граф ComfyUI для варианта index. refs: [{file, role, width, height}]."""
        raise NotImplementedError
