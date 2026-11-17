"""Реестр моделей. Новая модель = новый класс Recipe + строка в RECIPES."""
from .base import ROLES, ASPECTS
from .klein import Klein4B
from .wan import WanTI2V5B, WanI2V14B

RECIPES = {r.id: r for r in (Klein4B(), WanI2V14B(), WanTI2V5B())}


def get(model_id):
    return RECIPES.get(model_id)
