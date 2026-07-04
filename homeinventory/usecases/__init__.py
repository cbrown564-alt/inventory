"""Use-case profile registry."""

from __future__ import annotations

from functools import lru_cache

from ..schema import Inventory
from .base import UseCase

DEFAULT_USE_CASE = "tenancy"


@lru_cache
def _registry() -> dict[str, UseCase]:
    from .deepclean import DEEP_CLEAN
    from .tenancy import TENANCY
    return {TENANCY.key: TENANCY, DEEP_CLEAN.key: DEEP_CLEAN}


def __getattr__(name: str):
    if name == "REGISTRY":
        return _registry()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_use_case(key: str) -> UseCase:
    try:
        return _registry()[key]
    except KeyError:
        raise KeyError(f"unknown use case {key!r}; known: {sorted(_registry())}") from None


def use_case_for(inv: Inventory) -> UseCase:
    return get_use_case(inv.use_case)
