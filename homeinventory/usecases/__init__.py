"""Use-case profile registry."""

from __future__ import annotations

from ..schema import Inventory
from .base import UseCase
from .deepclean import DEEP_CLEAN
from .tenancy import TENANCY

DEFAULT_USE_CASE = "tenancy"

REGISTRY: dict[str, UseCase] = {
    TENANCY.key: TENANCY,
    DEEP_CLEAN.key: DEEP_CLEAN,
}


def get_use_case(key: str) -> UseCase:
    try:
        return REGISTRY[key]
    except KeyError:
        raise KeyError(f"unknown use case {key!r}; known: {sorted(REGISTRY)}") from None


def use_case_for(inv: Inventory) -> UseCase:
    return get_use_case(inv.use_case)
