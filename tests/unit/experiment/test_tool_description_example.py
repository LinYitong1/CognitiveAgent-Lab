"""R2 修订（诊断修复 F1）一致性测试：description 内嵌示例与真实 schema 逐字段一致。

断言组（契约 §5.1 R2 修订约束）：
1. 示例本身可被实际 ExperimentSpec Pydantic 模型校验，且 validate_spec → valid=true
   零错误零警告（"经过验证的示例"的可执行证据）；
2. description 确实包含该示例（模块级常量单一来源，防漂移）；
3. 该 description 原样出现在发送给 LLM 的 tools schema（registry.get_schemas()）中；
4. description 为纯 ASCII（R2 核心：消除转义密集的 schema 形态）；
5. 长度预算：软 ≤700 / 硬 ≤900 字符（R2 口径，取代 R1 的 1600/2400）；
6. 结构说明覆盖全部必需顶层键（不得为字符预算省略必需字段）。

文件名含 "tool_" 以便 PA-7 的 -k "tool_" 过滤一并命中。
"""

from __future__ import annotations

import json

from src.agent.registry import ToolRegistry
from src.config import Settings
from src.experiment.schemas import ExperimentSpec
from src.experiment.validation import validate_spec
from src.tools import experiment_tools

DESCRIPTION_SOFT_BUDGET = 700
DESCRIPTION_HARD_BUDGET = 900
REQUIRED_TOP_KEYS = ("schema_version", "name", "seed", "factors", "blocks", "responses")


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
    # 反包装指令在场（PA-14 失败模式 B 的直接对症文本，R2 英文版）
    assert "no wrapper" in spec.description


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
    assert "no wrapper" in validate_description


def test_description_is_pure_ascii() -> None:
    """R2 核心：description 纯 ASCII（ord(c) < 128，消除 \\uXXXX 转义密集形态）。"""
    spec = experiment_tools.build_validate_spec(Settings())
    non_ascii = [c for c in spec.description if ord(c) >= 128]
    assert not non_ascii, f"description 含非 ASCII 字符: {non_ascii[:10]}"


def test_description_length_budget() -> None:
    """token 预算护栏：软 ≤700（告警阈值），硬 ≤900（拒绝阈值）。"""
    spec = experiment_tools.build_validate_spec(Settings())
    length = len(spec.description)
    assert length <= DESCRIPTION_HARD_BUDGET, f"description 超过硬预算: {length} chars"
    assert length <= DESCRIPTION_SOFT_BUDGET, (
        f"description 超过软预算: {length} chars（需 Architect 复核示例精简）"
    )


def test_description_covers_required_top_keys() -> None:
    """结构说明不得为字符预算省略必需顶层键（契约 R2 约束 5）。"""
    spec = experiment_tools.build_validate_spec(Settings())
    for key in REQUIRED_TOP_KEYS:
        assert key in spec.description, f"结构说明缺失必需键: {key}"
