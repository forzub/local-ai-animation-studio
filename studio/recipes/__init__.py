"""Реестр моделей. Новая модель = новый класс Recipe + строка в RECIPES."""
from .base import ROLES, ASPECTS
from .klein import Klein4B
from .wan import WanTI2V5B, WanI2V14B
from .images import QwenImage21, QwenEdit2509, ZImageTurbo, Chroma1HD

RECIPES = {r.id: r for r in (QwenImage21(), Klein4B(), ZImageTurbo(), QwenEdit2509(), Chroma1HD(), WanI2V14B(), WanTI2V5B())}


def get(model_id):
    return RECIPES.get(model_id)
