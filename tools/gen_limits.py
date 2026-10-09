"""根据 schemas/ 生成规范附录 B（数值上限汇总）。

用法：
  python tools/gen_limits.py           重新生成 spec/附录B-数值上限.md
  python tools/gen_limits.py --check   只检查附录是否与 Schema 一致，不一致时以非零状态退出

附录 B 由本工具生成，不要手工编辑；修改上限时改 Schema，再重新生成（规范 7.5）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"
TARGET = ROOT / "spec" / "附录B-数值上限.md"

KEYWORDS = {
    "minLength": "最短 {} 个字符",
    "maxLength": "最长 {} 个字符",
    "minItems": "至少 {} 项",
    "maxItems": "至多 {} 项",
    "minProperties": "至少 {} 个键",
    "maxProperties": "至多 {} 个键",
    "minimum": "≥ {}",
    "maximum": "≤ {}",
    "exclusiveMinimum": "> {}",
    "exclusiveMaximum": "< {}",
}
SKIP_SEGMENTS = {"properties", "anyOf", "oneOf", "allOf", "if", "then", "else"}


def field_name(segments: list[str]) -> str:
    """把 JSON Pointer 片段转成便于阅读的字段路径，例如 properties/nodes/items/properties/id -> nodes[].id。"""
    parts: list[str] = []
    skip_index = False
    for seg in segments:
        if skip_index:
            skip_index = False
            continue
        if seg in ("anyOf", "oneOf", "allOf"):
            skip_index = True
            continue
        if seg in SKIP_SEGMENTS:
            continue
        if seg == "$defs":
            parts.append("#")
            continue
        if seg == "items":
            parts[-1:] = [(parts[-1] if parts else "") + "[]"]
            continue
        if seg == "additionalProperties":
            parts.append("<值>")
            continue
        if seg == "propertyNames":
            parts.append("<键>")
            continue
        if parts and parts[-1] == "#":
            parts[-1] = f"#{seg}"
        else:
            parts.append(seg)
    return ".".join(parts) or "（根）"


def collect() -> list[tuple[str, str, str]]:
    rows = []
    for path in sorted(SCHEMAS.rglob("*.json")):
        schema_name = path.relative_to(SCHEMAS).as_posix()

        def walk(node, segments):
            if isinstance(node, dict):
                limits = [KEYWORDS[k].format(node[k]) for k in KEYWORDS
                          if k in node and isinstance(node[k], (int, float)) and not isinstance(node[k], bool)]
                if limits:
                    rows.append((schema_name, field_name(segments), "，".join(limits)))
                for key, value in node.items():
                    walk(value, segments + [key])
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, segments + [str(i)])

        walk(json.loads(path.read_text(encoding="utf-8")), [])
    return rows


def render() -> str:
    lines = [
        "# 附录 B 数值上限",
        "",
        "> 状态：草案",
        "",
        "本附录由 `tools/gen_limits.py` 根据 `schemas/` 生成，汇总各数据结构的长度、数量与取值上限，"
        "与正文具有同等规范效力。修改上限时**必须**修改 Schema 并重新生成本附录（见 7.5）。",
        "",
        "字段路径中，`[]` 表示数组元素，`#名称` 表示 Schema 内的共享定义，`<键>`、`<值>` 分别表示对象的键与值。",
        "",
        "| Schema | 字段 | 约束 |",
        "|---|---|---|",
    ]
    for schema_name, field, limits in collect():
        lines.append(f"| `{schema_name}` | `{field}` | {limits} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    content = render()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != content:
            print(f"{TARGET.relative_to(ROOT).as_posix()} 与 schemas/ 不一致，请运行 python tools/gen_limits.py 重新生成")
            return 1
        print("附录 B 与 schemas/ 一致")
        return 0
    TARGET.write_text(content, encoding="utf-8", newline="\n")
    print(f"已生成 {TARGET.relative_to(ROOT).as_posix()}（{content.count(chr(10)) - 10} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
