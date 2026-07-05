"""Use-case profile registry."""

from __future__ import annotations

import logging
from functools import lru_cache

from ..schema import Inventory
from .base import UseCase

log = logging.getLogger(__name__)

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
    """Profile for an inventory. Unknown keys (a file from a newer or foreign
    version) degrade to the tenancy default rather than crashing rendering —
    the same tolerance Inventory.from_json shows for unknown fields."""
    try:
        return _registry()[inv.use_case]
    except KeyError:
        log.warning("unknown use_case %r in inventory — falling back to %r",
                    inv.use_case, DEFAULT_USE_CASE)
        return _registry()[DEFAULT_USE_CASE]
