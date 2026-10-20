"""canonical JSON 序列化与 SHA-256 指纹（契约 §6.1/§6.3，冻结）。

- canonical_json 五参数一字不差：sort_keys / ensure_ascii=False / 紧凑分隔符 / allow_nan=False；
- 指纹全部为完整 SHA-256（64 小写 hex，CR-2），禁止 [:8] 截断；
- trials 指纹计算路径禁止 float（Trial 全部字段为 int/str/空 dict）。
"""

from __future__ import annotations

import hashlib
import json


def canonical_json(obj: object) -> str:
    """canonical JSON：键排序、无空白、UTF-8、禁止 NaN/Inf（序列化即抛错）。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha256_hex(text: str) -> str:
    """SHA-256 完整十六进制指纹（64 小写 hex）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_hex_bytes(data: bytes) -> str:
    """SHA-256 完整十六进制指纹（字节输入）。"""
    return hashlib.sha256(data).hexdigest()
