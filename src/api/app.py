"""FastAPI 应用入口（M0：仅 /health 端点）。"""

from __future__ import annotations

from fastapi import FastAPI

from src.config import get_settings

app = FastAPI(title="CognitiveAgent Lab")

# M0-3 依据：无 key 环境下配置可正常加载（构造失败会在 import 时暴露）
get_settings()


@app.get("/health")
def health() -> dict[str, str]:
    """健康检查：body 精确为 {"status":"ok"}。"""
    return {"status": "ok"}
