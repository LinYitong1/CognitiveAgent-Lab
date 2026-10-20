"""R1 修订（PA-14 修复选项 A）一致性测试：description 内嵌示例与真实 schema 逐字段一致。

四项断言组（契约 §5.1 R1 修订约束）：
1. 示例本身可被实际 ExperimentSpec Pydantic 模型校验，且 validate_spec → valid=true
   零错误零警告（"经过验证的示例"的可执行证据）；
2. description 确实包含该示例（模块级常量单一来源，防漂移）；
3. 该 description 原样出现在发送给 LLM 的 tools schema（registry.get_schemas()）中；
4. description 长度预算（软 ≤1600 / 硬 ≤2400 字符，qwen2.5:7b ctx=8192 token 控制）。

文件名含 "tool_" 以便 PA-7 的 -k "tool_" 过滤一并命中。
"""

from __future__ import annotations

import json

from src.agent.registry import ToolRegistry
from src.config import Settings
from src.experiment.schemas import ExperimentSpec
from src.experiment.validation import validate_spec
from src.tools import experiment_tools

DESCRIPTION_SOFT_BUDGET = 1600
DESCRIPTION_HARD_BUDGET = 2400


def test_description_example_validates_against_real_schema() -> None:
    """示例经 json.loads → ExperimentSpec.model_validate → validate_spec 全部通过。"""
    example = json.loads(experiment_tools._SPEC_EXAMPLE_JSON)
    # Pydantic 结构校验（V1~V9 全部在场）
    ExperimentSpec.model_validate(example)
    # 验证层语义校验（C1~C3 等）
    result = validate_spec(example)
    assert result.valid is True
    assert result.errors == []
    assert result.warnings == []


def test_description_contains_example_constant() -> None:
    """description 内嵌模块级常量示例（单一来源，非两处抄写）。"""
    spec = experiment_tools.build_validate_spec(Settings())
    assert experiment_tools._SPEC_EXAMPLE_JSON in spec.description
    # 关键反包装指令在场（PA-14 失败模式 B 的直接对症文本）
    assert "禁止再包一层" in spec.description


def test_description_reaches_llm_tools_schema() -> None:
    """示例与反包装指令确实进入发送给 LLM 的 tools schema。"""
    registry = ToolRegistry()
    registry.register(experiment_tools.build_validate_spec(Settings()))
    registry.register(experiment_tools.build_generate_spec(Settings()))
    registry.register(experiment_tools.build_export_spec(Settings()))

    schemas = {s["function"]["name"]: s["function"]["description"] for s in registry.get_schemas()}
    assert set(schemas) == {"validate_experiment", "generate_trials", "export_experiment"}
    validate_description = schemas["validate_experiment"]
    assert experiment_tools._SPEC_EXAMPLE_JSON in validate_description
    assert "禁止再包一层" in validate_description


def test_description_length_budget() -> None:
    """token 预算护栏：软 ≤1600（告警阈值），硬 ≤2400（拒绝阈值）。"""
    spec = experiment_tools.build_validate_spec(Settings())
    length = len(spec.description)
    assert length <= DESCRIPTION_HARD_BUDGET, f"description 超过硬预算: {length} chars"
    assert length <= DESCRIPTION_SOFT_BUDGET, (
        f"description 超过软预算: {length} chars（需 Architect 复核示例精简）"
    )
