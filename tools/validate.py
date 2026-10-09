"""Mentorbit 插件包校验工具（规范 0.1）。

用法：python tools/validate.py <插件包目录> [<插件包目录> ...]

先自检 schemas/ 下全部 Schema，再逐个检查插件包：清单、路径、权限、贡献之间的引用、
对象类型 Schema、渲染器入口、内容包数据（引用完整性、课程图无环、受限 Markdown）以及完整性文件。
Schema 无法表达的规则都在这里实现；规范第 07 章要求规范性规则必须有对应校验。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"
MANIFEST_NAME = "mentorbit.plugin.json"
INTEGRITY_NAME = "mentorbit.integrity.json"
SIGNATURE_NAME = "mentorbit.signature.json"  # 规范 8.2 预留，签名对象是完整性文件，因而不计入完整性清单

# 规范 2.2：每个权限可申请的最低信任等级
TIER_ORDER = ["community", "verified", "official"]
INPUT_SCHEMA_KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "items", "enum", "description",
    "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems",
}
INPUT_SCHEMA_TYPES = {"string", "number", "integer", "boolean", "array", "object"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
REF_RE = re.compile(r"^(?:(?P<plugin>[a-z][a-z0-9-]{1,38}\.[a-z][a-z0-9-]{1,38})/)?(?P<pack>[a-z][a-z0-9_]{1,31})#(?P<entry>[a-z0-9][a-z0-9_-]{0,63})$")
HTML_TAG_RE = re.compile(r"<\s*/?\s*[A-Za-z!][^>]*>")
MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
MD_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE_RE = re.compile(r"(^|\n)(```|~~~).*?(\n\2[^\n]*)(?=\n|$)", re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def permission_min_tier(permission_id: str) -> str:
    if permission_id in ("storage.plugin", "model.invoke") or permission_id.startswith("network:"):
        return "community"
    if permission_id == "learner.read:human" or permission_id.startswith("evidence.propose:"):
        return "official"
    return "verified"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class Report:
    def __init__(self, name: str):
        self.name = name
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")


_UNREADABLE = object()


def read_text(path: Path, report: Report, where: str) -> str | None:
    """读取 UTF-8 文本；编码或文件系统错误记为校验错误，而不是让校验器崩溃。"""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        report.error(where, "不是 UTF-8 编码的文本")
    except OSError as exc:
        report.error(where, f"无法读取：{exc.strerror or type(exc).__name__}")
    return None


def read_json(path: Path, report: Report, where: str):
    """读取 JSON；失败时报告错误并返回 _UNREADABLE（JSON 本身可以是 null，不能用 None 表示失败）。"""
    text = read_text(path, report, where)
    if text is None:
        return _UNREADABLE
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        report.error(where, f"不是合法的 JSON：{exc}")
        return _UNREADABLE


def schema_errors(validator: Draft202012Validator, instance) -> list[str]:
    out = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(p) for p in err.absolute_path) or "(根)"
        out.append(f"{location}: {err.message}")
    return out


def build_registry() -> tuple[Registry, dict[str, dict]]:
    schemas = {}
    resources = []
    for path in sorted(SCHEMAS.rglob("*.json")):
        schema = load_json(path)
        schemas[path.relative_to(SCHEMAS).as_posix()] = schema
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources), schemas


def self_check(registry: Registry, schemas: dict[str, dict]) -> list[str]:
    """校验仓库自带的 Schema 本身合法，且跨文件 $ref 都能解析。"""
    problems = []
    for name, schema in schemas.items():
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # noqa: BLE001 - 汇总报告即可
            problems.append(f"schemas/{name}: 不是合法的 JSON Schema：{exc}")
            continue

        def walk(node, base=schema["$id"]):
            if isinstance(node, dict):
                ref = node.get("$ref")
                if isinstance(ref, str) and not ref.startswith("#"):
                    try:
                        registry.resolver(base).lookup(ref)
                    except Exception as exc:  # noqa: BLE001
                        problems.append(f"schemas/{name}: 无法解析 $ref {ref}：{exc}")
                for value in node.values():
                    walk(value, base)
            elif isinstance(node, list):
                for value in node:
                    walk(value, base)

        walk(schema)
    return problems


def safe_path(package: Path, rel: str, report: Report, where: str) -> Path | None:
    """规范 1.1：相对路径、不得越出包目录、不得经符号链接指向包外。"""
    if rel.startswith("/") or "\\" in rel or ":" in rel or "\x00" in rel or ".." in rel.split("/"):
        report.error(where, f"非法路径 {rel!r}")
        return None
    target = package / rel
    try:
        resolved = target.resolve(strict=True)
    except FileNotFoundError:
        report.error(where, f"文件不存在 {rel}")
        return None
    except OSError as exc:
        report.error(where, f"无法访问 {rel}：{exc.strerror or type(exc).__name__}")
        return None
    if package.resolve() not in resolved.parents and resolved != package.resolve():
        report.error(where, f"路径越出包目录 {rel}")
        return None
    if not resolved.is_file():
        report.error(where, f"不是普通文件 {rel}")
        return None
    return resolved


def check_localized(value, default_locale: str, max_chars: int | None, report: Report, where: str) -> None:
    texts = [value] if isinstance(value, str) else list(value.values()) if isinstance(value, dict) else []
    if isinstance(value, dict) and default_locale not in value:
        report.error(where, f"本地化文本缺少 defaultLocale（{default_locale}）对应的键")
    if max_chars:
        for text in texts:
            if len(text) > max_chars:
                report.error(where, f"超过 {max_chars} 个字符")


def check_input_schema(node, report: Report, where: str) -> None:
    """规范 5.3：inputSchema 只能使用规定的关键字子集。"""
    if not isinstance(node, dict):
        report.error(where, "必须是对象")
        return
    extra = set(node) - INPUT_SCHEMA_KEYWORDS
    if extra:
        report.error(where, f"使用了子集之外的关键字 {sorted(extra)}")
    node_type = node.get("type")
    if node_type is not None and node_type not in INPUT_SCHEMA_TYPES:
        report.error(where, f"type 取值 {node_type!r} 不在允许范围内")
    if node_type == "object" and node.get("additionalProperties") is not False:
        report.error(where, "对象类型必须声明 additionalProperties: false")
    for key, sub in (node.get("properties") or {}).items():
        check_input_schema(sub, report, f"{where}/properties/{key}")
    if "items" in node:
        check_input_schema(node["items"], report, f"{where}/items")
    for key in node.get("required", []):
        if key not in (node.get("properties") or {}):
            report.error(where, f"required 中的 {key!r} 未在 properties 中定义")


def check_object_schema(path: Path, report: Report, where: str) -> None:
    """规范 5.1：2020-12、根为 object 且 additionalProperties: false、不得引用包外。"""
    try:
        schema = load_json(path)
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # noqa: BLE001
        report.error(where, f"对象 Schema 无效：{exc}")
        return
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        report.error(where, "对象 Schema 根节点必须是 type: object 且 additionalProperties: false")

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and not ref.startswith("#"):
                report.error(where, f"不得使用指向包外的 $ref：{ref}")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)


def strip_code(text: str) -> str:
    return INLINE_CODE_RE.sub("", FENCE_RE.sub("\n", text))


def check_markdown(text: str, package: Path, report: Report, where: str) -> None:
    """规范 3.6：受限 Markdown（不含原始 HTML、图片仅限包内位图、链接仅限 https）。"""
    prose = strip_code(text)
    if HTML_TAG_RE.search(prose):
        report.error(where, "受限 Markdown 不得包含原始 HTML")
    for target in MD_IMAGE_RE.findall(prose):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            report.error(where, f"图片必须引用包内文件，不得引用 {target}")
        elif Path(target).suffix.lower() not in IMAGE_EXT:
            report.error(where, f"图片格式不允许：{target}")
        else:
            safe_path(package, target, report, where)
    for target in MD_LINK_RE.findall(prose):
        if not target.startswith("https://"):
            report.error(where, f"链接只允许 https：{target}")


def acyclic(nodes, edges) -> list[str] | None:
    """返回一个环（节点列表），无环时返回 None。"""
    graph = defaultdict(list)
    for a, b in edges:
        graph[a].append(b)
    color = dict.fromkeys(nodes, 0)
    stack: list[str] = []

    def dfs(n):
        color[n] = 1
        stack.append(n)
        for m in graph[n]:
            if color.get(m) == 1:
                return stack[stack.index(m):] + [m]
            if color.get(m) == 0:
                found = dfs(m)
                if found:
                    return found
        stack.pop()
        color[n] = 2
        return None

    sys.setrecursionlimit(max(10000, len(nodes) * 4))
    for n in nodes:
        if color[n] == 0:
            found = dfs(n)
            if found:
                return found
    return None


class ContentIndex:
    """同一插件内可被引用的条目：pack_id -> (kind, {entry_id})。"""

    def __init__(self):
        self.packs: dict[str, tuple[str, set[str]]] = {}
        self.invalid: set[str] = set()  # 自身未通过校验的内容包，指向它的引用不再重复报错

    def resolve(self, ref: str, plugin_id: str, report: Report, where: str, expect_kind: str | None = None) -> None:
        m = REF_RE.match(ref)
        if not m:
            report.error(where, f"引用格式错误：{ref}")
            return
        if m["plugin"] and m["plugin"] != plugin_id:
            report.notes.append(f"{where}: 跨插件引用 {ref}，需在安装后由宿主解析")
            return
        if m["pack"] in self.invalid:
            return
        pack = self.packs.get(m["pack"])
        if pack is None:
            report.error(where, f"引用了不存在的内容包 {m['pack']}")
            return
        kind, entries = pack
        if expect_kind and kind != expect_kind:
            report.error(where, f"引用 {ref} 应指向 {expect_kind}，实际是 {kind}")
        if m["entry"] not in entries:
            report.error(where, f"引用的条目不存在：{ref}")


def check_course_graph(data: dict, report: Report, where: str) -> set[str]:
    ids = [n["id"] for n in data["nodes"]]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        report.error(where, f"节点 ID 重复：{sorted(dup)}")
    node_set = set(ids)
    seen = set()
    prereq = []
    for i, e in enumerate(data["edges"]):
        w = f"{where}/edges/{i}"
        if e["from"] not in node_set or e["to"] not in node_set:
            report.error(w, f"边引用了不存在的节点 {e['from']} -> {e['to']}")
        if e["from"] == e["to"]:
            report.error(w, "边的两端不得相同")
        key = (e["from"], e["to"], e["relation"])
        if e["relation"] == "co_learn":
            key = (*sorted((e["from"], e["to"])), "co_learn")
        if key in seen:
            report.error(w, "同一对节点之间同一种关系重复")
        seen.add(key)
        if e["relation"] in ("hard_prereq", "soft_prereq"):
            prereq.append((e["from"], e["to"]))
    cycle = acyclic(ids, prereq)
    if cycle:
        report.error(where, f"前置关系存在环：{' -> '.join(cycle)}")
    return node_set


def check_question_bank(data: dict, package: Path, report: Report, where: str) -> set[str]:
    ids = [q["id"] for q in data["questions"]]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        report.error(where, f"题目 ID 重复：{sorted(dup)}")
    id_set = set(ids)
    variant = {}
    for i, q in enumerate(data["questions"]):
        w = f"{where}/questions/{i}({q['id']})"
        option_ids = [o["id"] for o in q.get("options", [])]
        if len(option_ids) != len(set(option_ids)):
            report.error(w, "选项 ID 重复")
        for oid in q["answer"].get("optionIds", []):
            if oid not in option_ids:
                report.error(w, f"答案引用了不存在的选项 {oid}")
        if q["type"] == "single_choice" and len(q["answer"].get("optionIds", [])) != 1:
            report.error(w, "单选题答案必须恰好一项")
        if "variantOf" in q:
            if q["variantOf"] == q["id"]:
                report.error(w, "variantOf 不得指向自身")
            elif q["variantOf"] not in id_set:
                report.error(w, f"variantOf 指向不存在的题目 {q['variantOf']}")
            else:
                variant[q["id"]] = q["variantOf"]
        texts = [("stem", q["stem"]), ("explanation", q["explanation"])]
        texts += [(f"hints/{k}", h) for k, h in enumerate(q.get("hints", []))]
        texts += [(f"options/{o['id']}", o["text"]) for o in q.get("options", [])]
        if "reference" in q["answer"]:
            texts.append(("answer/reference", q["answer"]["reference"]))
        for field, text in texts:
            check_markdown(text, package, report, f"{w}/{field}")
    cycle = acyclic(list(id_set), list(variant.items()))
    if cycle:
        report.error(where, f"variantOf 存在环：{' -> '.join(cycle)}")
    return id_set


def check_package(package: Path, validators: dict[str, Draft202012Validator]) -> Report:
    report = Report(str(package))
    manifest_path = package / MANIFEST_NAME
    if not manifest_path.is_file():
        report.error(MANIFEST_NAME, "缺少清单文件")
        return report
    manifest = read_json(manifest_path, report, MANIFEST_NAME)
    if manifest is _UNREADABLE:
        return report

    for problem in schema_errors(validators["manifest.schema.json"], manifest):
        report.error(MANIFEST_NAME, problem)
    if report.errors:
        return report  # 结构不合法时，后续语义检查没有意义

    plugin_id = manifest["id"]
    locale = manifest["defaultLocale"]
    contributes = manifest["contributes"]
    check_localized(manifest["displayName"], locale, 40, report, "displayName")
    check_localized(manifest["description"], locale, 200, report, "description")

    total = sum(len(v) for v in contributes.values())
    if total == 0:
        report.error("contributes", "至少需要一项贡献")
    for ep in manifest.get("requires", {}).get("extensionPoints", []):
        if not contributes.get(ep):
            report.warn("requires", f"声明必需扩展点 {ep}，但没有对应的贡献")

    # 权限
    permissions = manifest.get("permissions", [])
    perm_ids = [p["id"] for p in permissions]
    if len(perm_ids) != len(set(perm_ids)):
        report.error("permissions", "权限重复申请")
    if sum(p.startswith("network:") for p in perm_ids) > 5:
        report.error("permissions", "network 权限最多 5 个")
    min_tier = max((permission_min_tier(p) for p in perm_ids), key=TIER_ORDER.index, default="community")
    report.notes.append(f"按申请的权限，至少需要信任等级：{min_tier}")

    # 图标与运行时
    if "icon" in manifest:
        icon = safe_path(package, manifest["icon"], report, "icon")
        if icon:
            try:
                if icon.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                    report.error("icon", "不是 PNG 文件")
            except OSError as exc:
                report.error("icon", f"无法读取：{exc.strerror or type(exc).__name__}")
    if "runtime" in manifest:
        safe_path(package, manifest["runtime"]["entry"], report, "runtime.entry")
        if not contributes.get("tools"):
            report.warn("runtime", "声明了 runtime，但没有工具贡献")

    # 每类贡献内 ID 唯一
    for kind, items in contributes.items():
        ids = [item["id"] for item in items]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            report.error(f"contributes.{kind}", f"ID 重复：{sorted(dup)}")
        for item in items:
            if "title" in item:
                check_localized(item["title"], locale, None, report, f"contributes.{kind}.{item['id']}.title")

    object_types = {o["id"] for o in contributes.get("objectTypes", [])}
    for o in contributes.get("objectTypes", []):
        path = safe_path(package, o["schema"], report, f"objectTypes.{o['id']}.schema")
        if path:
            check_object_schema(path, report, f"objectTypes.{o['id']}.schema")

    for t in contributes.get("tools", []):
        w = f"tools.{t['id']}"
        check_input_schema(t["inputSchema"], report, f"{w}.inputSchema")
        for ot in t.get("outputObjectTypes", []):
            if ot not in object_types:
                report.error(w, f"outputObjectTypes 引用了未声明的对象类型 {ot}")
        if t["effect"] == "read_only" and t.get("outputObjectTypes"):
            report.error(w, "effect 为 read_only 的工具不得产出对象")

    for r in contributes.get("renderers", []):
        w = f"renderers.{r['id']}"
        for ot in r["objectTypes"]:
            if "/" in ot:
                if f"objects.read:{ot}" not in perm_ids:
                    report.error(w, f"渲染其他插件的类型 {ot} 需要申请 objects.read:{ot}")
            elif ot not in object_types:
                report.error(w, f"引用了未声明的对象类型 {ot}")
        if r.get("minHeight") and r.get("maxHeight") and r["minHeight"] > r["maxHeight"]:
            report.error(w, "minHeight 大于 maxHeight")
        entry = safe_path(package, r["entry"], report, f"{w}.entry")
        html = read_text(entry, report, f"{w}.entry") if entry else None
        if html is not None:
            # 规范 4.2：CSP 禁止内联脚本与包外资源
            if re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html, re.I):
                report.error(f"{w}.entry", "沙箱 CSP 下内联脚本不会执行，脚本必须放在包内文件中")
            for src in re.findall(r"(?:src|href)\s*=\s*[\"']([^\"']+)[\"']", html, re.I):
                if re.match(r"^[a-z][a-z0-9+.-]*:", src, re.I) or src.startswith("//"):
                    report.error(f"{w}.entry", f"不得引用包外资源：{src}")
                else:
                    safe_path(package, (Path(r["entry"]).parent / src).as_posix(), report, f"{w}.entry")
            if re.search(r"\bon[a-z]+\s*=", html, re.I):
                report.error(f"{w}.entry", "沙箱 CSP 下内联事件处理属性不会执行")

    # 内容包：先建索引，再检查引用
    index = ContentIndex()
    loaded = []
    for c in contributes.get("contentPacks", []):
        w = f"contentPacks.{c['id']}"
        path = safe_path(package, c["path"], report, w)
        if not path:
            continue
        data = read_json(path, report, w)
        if data is _UNREADABLE:
            index.invalid.add(c["id"])
            continue
        problems = schema_errors(validators[f"content/{c['kind']}.schema.json"], data)
        for problem in problems:
            report.error(w, problem)
        if problems:
            index.invalid.add(c["id"])
            continue
        if c["kind"] == "course-graph":
            entries = check_course_graph(data, report, w)
        elif c["kind"] == "question-bank":
            entries = check_question_bank(data, package, report, w)
        else:
            entries = {lec["id"] for lec in data["lectures"]}
        index.packs[c["id"]] = (c["kind"], entries)
        loaded.append((c, data, w))

    for c, data, w in loaded:
        if c["kind"] == "question-bank":
            for q in data["questions"]:
                for ref in q["nodes"]:
                    index.resolve(ref, plugin_id, report, f"{w}/{q['id']}/nodes", "course-graph")
        elif c["kind"] == "lecture-set":
            for lec in data["lectures"]:
                for ref in lec["nodes"]:
                    index.resolve(ref, plugin_id, report, f"{w}/{lec['id']}/nodes", "course-graph")
                md = safe_path(package, lec["path"], report, f"{w}/{lec['id']}/path")
                text = read_text(md, report, f"{w}/{lec['id']}/path") if md else None
                if text is not None:
                    check_markdown(text, package, report, f"{w}/{lec['id']}")

    # 容量（规范 1.1：宿主必须至少接受 20 MiB、5000 个文件）
    files = [p for p in package.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    size = sum(p.stat().st_size for p in files)
    if size > 20 * 1024 * 1024 or len(files) > 5000:
        report.warn("包", f"{len(files)} 个文件、{size} 字节，超过宿主必须接受的下限，可能被拒绝")

    # 完整性（规范 1.6）：存在时先按 Schema 校验格式，再逐一核对
    integrity_path = package / INTEGRITY_NAME
    if integrity_path.is_file():
        check_integrity(package, files, integrity_path, validators, report)
    else:
        report.notes.append(f"未包含 {INTEGRITY_NAME}，按开发目录处理（分发归档必须包含）")

    return report


def check_integrity(package: Path, files: list[Path], path: Path,
                    validators: dict[str, Draft202012Validator], report: Report) -> None:
    integrity = read_json(path, report, INTEGRITY_NAME)
    if integrity is _UNREADABLE:
        return
    problems = schema_errors(validators["integrity.schema.json"], integrity)
    for problem in problems:
        report.error(INTEGRITY_NAME, problem)
    if problems:
        return
    listed = integrity["files"]
    for name in (INTEGRITY_NAME, SIGNATURE_NAME):
        if name in listed:
            report.error(INTEGRITY_NAME, f"不得列出 {name}")
    actual = {p.relative_to(package).as_posix(): p for p in files
              if p.relative_to(package).as_posix() not in (INTEGRITY_NAME, SIGNATURE_NAME)}
    for rel in sorted(set(listed) | set(actual)):
        if rel in (INTEGRITY_NAME, SIGNATURE_NAME):
            continue
        if rel not in actual:
            report.error(INTEGRITY_NAME, f"列出但不存在：{rel}")
        elif rel not in listed:
            report.error(INTEGRITY_NAME, f"未列出的文件：{rel}")
        else:
            try:
                digest = hashlib.sha256(actual[rel].read_bytes()).hexdigest()
            except OSError as exc:
                report.error(INTEGRITY_NAME, f"无法读取 {rel}：{exc.strerror or type(exc).__name__}")
                continue
            if digest != listed[rel]:
                report.error(INTEGRITY_NAME, f"哈希不一致：{rel}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    registry, schemas = build_registry()
    problems = self_check(registry, schemas)
    if problems:
        print("Schema 自检失败：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print(f"Schema 自检通过（{len(schemas)} 个）")

    validators = {name: Draft202012Validator(schema, registry=registry) for name, schema in schemas.items()}
    failed = False
    for arg in argv:
        try:
            report = check_package(Path(arg), validators)
        except Exception as exc:  # noqa: BLE001 - 兜底：单个包的意外错误不影响其他包，并计为失败
            report = Report(arg)
            report.error("校验器内部错误", f"{type(exc).__name__}: {exc}")
        status = "失败" if report.errors else "通过"
        print(f"\n[{status}] {report.name}")
        for e in report.errors:
            print(f"  ✗ {e}")
        for w in report.warnings:
            print(f"  ! {w}")
        for n in report.notes:
            print(f"  · {n}")
        failed |= bool(report.errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
