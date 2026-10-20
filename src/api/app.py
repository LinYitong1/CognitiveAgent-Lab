"""FastAPI application entry (M0: only the /health endpoint)."""

from __future__ import annotations

from fastapi import FastAPI

from src.config import get_settings

app = FastAPI(title="CognitiveAgent Lab")

# M0-3 basis: the configuration loads fine in a key-less environment (a construction failure would surface at import time)
get_settings()


@app.get("/health")
def health() -> dict[str, str]:
    """Health check: the body is exactly {"status":"ok"}."""
    return {"status": "ok"}
