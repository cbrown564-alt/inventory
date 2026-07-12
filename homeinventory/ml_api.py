"""Shared VLM API availability checks (ML-E2 / ML-E8 production wiring)."""

from __future__ import annotations

import os


def vlm_api_available(model: str) -> bool:
    """True when credentials exist for *model*'s provider."""
    if model.startswith("claude"):
        return bool(
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("GEMINI_API_KEY"))
