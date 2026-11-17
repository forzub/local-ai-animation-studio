"""Реестр моделей. Новая модель = новый класс Recipe + строка в RECIPES."""
from .base import ROLES, ASPECTS
from .klein import Klein4B

RECIPES = {r.id: r for r in (Klein4B(),)}


def get(model_id):
    return RECIPES.get(model_id)
