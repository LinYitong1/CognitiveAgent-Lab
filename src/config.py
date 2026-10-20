"""应用配置：pydantic-settings 从环境变量与 .env 文件加载（ARCHITECTURE §7）。

env_file 路径受 ``CALC_AGENT_ENV_FILE`` 环境变量覆盖（默认 ``.env``），
设为 ``/dev/null`` 即完全绕开 .env 文件（无 key 环境验收依据）。
M0 阶段密钥字段可为空，不校验存在性。
"""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE: str = os.environ.get("CALC_AGENT_ENV_FILE", ".env")


class Settings(BaseSettings):
    """全局配置（字段与 .env.example 一一对应）。"""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "gpt-4o"
    calc_agent_max_steps: int = 25
    http_allowed_hosts: str = "example.com"
    data_sandbox_dir: str = "data"
    # SEARCH_EXHAUSTED 框架能力参数（契约 §4.2；Phase A 无消费路径，Phase B 序列约束消费）
    experiment_max_search_attempts: int = 100

    @property
    def allowed_hosts(self) -> list[str]:
        """逗号分隔的域名白名单解析为列表。"""
        return [host.strip() for host in self.http_allowed_hosts.split(",") if host.strip()]


def get_settings() -> Settings:
    """构造 Settings 实例（无 key 环境下也可正常构造，M0-3 依据）。"""
    return Settings()
