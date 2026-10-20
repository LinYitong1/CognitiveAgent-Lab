"""experiment 包：Phase A 通用实验引擎（契约 docs/handoff/architect-phaseA-contract.md）。

模块组成：
- schemas.py      ExperimentSpec 全层级 Pydantic 模型（契约 §2 字段表 + V1~V9）
- canonical.py    canonical JSON 序列化与 SHA-256 指纹（契约 §6.1/§6.3）
- validation.py   约束语义验证与错误码枚举（契约 §4）
- generation.py   确定性生成引擎（契约 §3 九步算法）
- export.py       ExperimentBundle 组装（契约 §6.2）
- verify.py       免生成器独立验证 CLI（契约 §6.4）

分层（契约 §8.4）：experiment 层只依赖 src/models、src/config 与标准库；
禁止 import src.agent / src.tools / src.api / src.services / src.storage。
组合注册入口位于 src/agent/experiment_registry.py（agent 层，契约 §5.4）。
"""
