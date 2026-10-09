"""校验工具的反例测试：每个用例在示例包的副本上制造一处违规，确认 validate.py 能报出来。
另含文档一致性测试：规范正文中的示例与方法表必须与 Schema、校验器保持一致（规范 7.5）。

用法：python -m unittest discover -s tools -p "test_*.py"
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate  # noqa: E402

EXAMPLES = validate.ROOT / "examples"
REGISTRY, SCHEMAS = validate.build_registry()
VALIDATORS = {name: validate.Draft202012Validator(s, registry=REGISTRY) for name, s in SCHEMAS.items()}


class PackageCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def copy(self, example: str) -> Path:
        # 每次复制都放进新的子目录，同一测试中的多个子用例互不干扰
        target = Path(tempfile.mkdtemp(dir=self.tmp.name)) / example
        shutil.copytree(EXAMPLES / example, target, ignore=shutil.ignore_patterns("__pycache__"))
        return target

    @staticmethod
    def edit_json(path: Path, mutate) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def errors(self, package: Path) -> str:
        return "\n".join(validate.check_package(package, VALIDATORS).errors)

    def assertRejects(self, package: Path, fragment: str):
        errors = self.errors(package)
        self.assertIn(fragment, errors, f"预期包含“{fragment}”，实际错误：\n{errors or '（无）'}")


class ExamplesPass(PackageCase):
    def test_examples_have_no_errors(self):
        for example in ("intro-cs-content", "flashcard-renderer", "glossary-tool"):
            with self.subTest(example=example):
                self.assertEqual(self.errors(EXAMPLES / example), "")

    def test_repository_schemas_self_check(self):
        self.assertEqual(validate.self_check(REGISTRY, SCHEMAS), [])


class ManifestRules(PackageCase):
    def test_bad_plugin_id(self):
        pkg = self.copy("glossary-tool")
        self.edit_json(pkg / validate.MANIFEST_NAME, lambda m: m.update(id="Glossary"))
        self.assertRejects(pkg, "id")

    def test_localized_text_missing_default_locale(self):
        pkg = self.copy("glossary-tool")
        self.edit_json(pkg / validate.MANIFEST_NAME, lambda m: m.update(displayName={"en": "Glossary"}))
        self.assertRejects(pkg, "defaultLocale")

    def test_tools_require_runtime(self):
        pkg = self.copy("glossary-tool")
        self.edit_json(pkg / validate.MANIFEST_NAME, lambda m: m.pop("runtime"))
        self.assertRejects(pkg, "runtime")

    def test_network_requires_privacy_policy(self):
        pkg = self.copy("glossary-tool")
        self.edit_json(pkg / validate.MANIFEST_NAME, lambda m: m["permissions"].append(
            {"id": "network:https://api.example.com", "reason": "查词典"}))
        self.assertRejects(pkg, "privacyPolicy")

    def test_network_wildcard_rejected(self):
        pkg = self.copy("glossary-tool")
        self.edit_json(pkg / validate.MANIFEST_NAME, lambda m: (
            m.update(privacyPolicy="https://example.com/privacy"),
            m["permissions"].append({"id": "network:https://*.example.com", "reason": "查词典"})))
        self.assertRejects(pkg, "permissions")

    def test_path_traversal_rejected(self):
        pkg = self.copy("glossary-tool")
        self.edit_json(pkg / validate.MANIFEST_NAME, lambda m: m["runtime"].update(entry="../outside.py"))
        self.assertRejects(pkg, "runtime")

    def test_unknown_top_level_field(self):
        pkg = self.copy("glossary-tool")
        self.edit_json(pkg / validate.MANIFEST_NAME, lambda m: m.update(trustTier="official"))
        self.assertRejects(pkg, "trustTier")

    def test_input_schema_subset(self):
        pkg = self.copy("glossary-tool")
        self.edit_json(pkg / validate.MANIFEST_NAME, lambda m: m["contributes"]["tools"][0]["inputSchema"]
                       ["properties"]["term"].update(pattern="^[a-z]+$"))
        self.assertRejects(pkg, "子集之外的关键字")

    def test_undeclared_output_object_type(self):
        pkg = self.copy("glossary-tool")
        self.edit_json(pkg / validate.MANIFEST_NAME, lambda m: m["contributes"]["tools"][0].update(
            outputObjectTypes=["nope_type"]))
        self.assertRejects(pkg, "未声明的对象类型")

    def test_object_schema_must_close_additional_properties(self):
        pkg = self.copy("glossary-tool")
        self.edit_json(pkg / "schemas" / "glossary_entry.json", lambda s: s.pop("additionalProperties"))
        self.assertRejects(pkg, "additionalProperties")


class RendererRules(PackageCase):
    def test_inline_script_rejected(self):
        pkg = self.copy("flashcard-renderer")
        html = pkg / "renderer" / "index.html"
        html.write_text(html.read_text(encoding="utf-8").replace("</body>", "<script>alert(1)</script></body>"), encoding="utf-8")
        self.assertRejects(pkg, "内联脚本")

    def test_remote_resource_rejected(self):
        pkg = self.copy("flashcard-renderer")
        html = pkg / "renderer" / "index.html"
        html.write_text(html.read_text(encoding="utf-8").replace('src="main.js"', 'src="https://cdn.example.com/x.js"'), encoding="utf-8")
        self.assertRejects(pkg, "包外资源")

    def test_foreign_object_type_needs_permission(self):
        pkg = self.copy("flashcard-renderer")
        self.edit_json(pkg / validate.MANIFEST_NAME, lambda m: m["contributes"]["renderers"][0]["objectTypes"].append(
            "example.glossary/glossary_entry"))
        self.assertRejects(pkg, "objects.read:example.glossary/glossary_entry")


class ContentRules(PackageCase):
    def test_prereq_cycle_rejected(self):
        pkg = self.copy("intro-cs-content")
        self.edit_json(pkg / "content" / "graph.json", lambda g: g["edges"].append(
            {"from": "algorithms", "to": "variables", "relation": "soft_prereq"}))
        self.assertRejects(pkg, "前置关系存在环")

    def test_co_learn_does_not_count_as_cycle(self):
        pkg = self.copy("intro-cs-content")
        self.edit_json(pkg / "content" / "graph.json", lambda g: g["edges"].append(
            {"from": "algorithms", "to": "variables", "relation": "co_learn"}))
        self.assertEqual(self.errors(pkg), "")

    def test_edge_to_missing_node(self):
        pkg = self.copy("intro-cs-content")
        self.edit_json(pkg / "content" / "graph.json", lambda g: g["edges"].append(
            {"from": "variables", "to": "ghost", "relation": "hard_prereq"}))
        self.assertRejects(pkg, "不存在的节点")

    def test_answer_option_must_exist(self):
        pkg = self.copy("intro-cs-content")
        self.edit_json(pkg / "content" / "questions.json", lambda q: q["questions"][0]["answer"].update(optionIds=["z"]))
        self.assertRejects(pkg, "不存在的选项")

    def test_single_choice_exactly_one(self):
        pkg = self.copy("intro-cs-content")
        self.edit_json(pkg / "content" / "questions.json", lambda q: q["questions"][0]["answer"].update(optionIds=["a", "b"]))
        self.assertRejects(pkg, "questions")

    def test_variant_cycle_rejected(self):
        pkg = self.copy("intro-cs-content")
        self.edit_json(pkg / "content" / "questions.json", lambda q: q["questions"][0].update(variantOf="var-assign-2"))
        self.assertRejects(pkg, "variantOf 存在环")

    def test_node_reference_must_resolve(self):
        pkg = self.copy("intro-cs-content")
        self.edit_json(pkg / "content" / "questions.json", lambda q: q["questions"][0].update(nodes=["intro_graph#ghost"]))
        self.assertRejects(pkg, "引用的条目不存在")

    def test_raw_html_in_markdown_rejected(self):
        pkg = self.copy("intro-cs-content")
        self.edit_json(pkg / "content" / "questions.json", lambda q: q["questions"][0].update(
            stem="看图 <img src=x onerror=alert(1)>"))
        self.assertRejects(pkg, "原始 HTML")

    def test_html_inside_code_is_allowed(self):
        pkg = self.copy("intro-cs-content")
        self.edit_json(pkg / "content" / "questions.json", lambda q: q["questions"][0].update(
            stem="`<div>` 是什么标签？"))
        self.assertEqual(self.errors(pkg), "")

    def test_remote_image_rejected(self):
        pkg = self.copy("intro-cs-content")
        md = pkg / "content" / "lectures" / "variables.md"
        md.write_text(md.read_text(encoding="utf-8") + "\n![图](https://example.com/a.png)\n", encoding="utf-8")
        self.assertRejects(pkg, "图片必须引用包内文件")

    def test_non_https_link_rejected(self):
        pkg = self.copy("intro-cs-content")
        md = pkg / "content" / "lectures" / "variables.md"
        md.write_text(md.read_text(encoding="utf-8") + "\n[链接](http://example.com)\n", encoding="utf-8")
        self.assertRejects(pkg, "链接只允许 https")

    def test_format_must_match_kind(self):
        pkg = self.copy("intro-cs-content")
        self.edit_json(pkg / "content" / "graph.json", lambda g: g.update(format="mentorbit.question-bank/0.1"))
        self.assertRejects(pkg, "format")


class IntegrityRules(PackageCase):
    def write_integrity(self, pkg: Path) -> Path:
        files = {p.relative_to(pkg).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in pkg.rglob("*") if p.is_file()}
        path = pkg / validate.INTEGRITY_NAME
        path.write_text(json.dumps({"algorithm": "sha256", "files": files}), encoding="utf-8")
        return path

    def test_valid_integrity_passes(self):
        pkg = self.copy("intro-cs-content")
        self.write_integrity(pkg)
        self.assertEqual(self.errors(pkg), "")

    def test_tampered_file_detected(self):
        pkg = self.copy("intro-cs-content")
        self.write_integrity(pkg)
        md = pkg / "content" / "lectures" / "variables.md"
        md.write_text(md.read_text(encoding="utf-8") + "\n被篡改\n", encoding="utf-8")
        self.assertRejects(pkg, "哈希不一致")

    def test_extra_file_detected(self):
        pkg = self.copy("intro-cs-content")
        self.write_integrity(pkg)
        (pkg / "extra.txt").write_text("x", encoding="utf-8")
        self.assertRejects(pkg, "未列出的文件")

    def mutate_integrity(self, mutate) -> Path:
        pkg = self.copy("intro-cs-content")
        path = self.write_integrity(pkg)
        data = json.loads(path.read_text(encoding="utf-8"))
        result = mutate(data)
        path.write_text(result if isinstance(result, str) else json.dumps(result), encoding="utf-8")
        return pkg

    def test_format_rules(self):
        """规范 1.6：algorithm 必须为 sha256、摘要为小写十六进制、不得有其他字段；格式错误时报告而不崩溃。"""
        cases = {
            "algorithm 为 md5": (lambda d: {**d, "algorithm": "md5"}, "algorithm"),
            "缺少 algorithm": (lambda d: {"files": d["files"]}, "algorithm"),
            "摘要为大写": (lambda d: {**d, "files": {k: v.upper() for k, v in d["files"].items()}}, "files"),
            "多出字段": (lambda d: {**d, "note": "x"}, "note"),
            "files 为数组": (lambda d: {**d, "files": list(d["files"])}, "files"),
            "不是合法 JSON": (lambda d: "{bad", "不是合法的 JSON"),
            "路径越出包目录": (lambda d: {**d, "files": {**d["files"], "../x": "0" * 64}}, "files"),
        }
        for name, (mutate, fragment) in cases.items():
            with self.subTest(name):
                self.assertRejects(self.mutate_integrity(mutate), fragment)

    def test_signature_file_is_excluded(self):
        pkg = self.copy("intro-cs-content")
        self.write_integrity(pkg)
        (pkg / validate.SIGNATURE_NAME).write_text("{}", encoding="utf-8")
        self.assertEqual(self.errors(pkg), "")

    def test_listing_reserved_names_rejected(self):
        pkg = self.mutate_integrity(lambda d: {**d, "files": {**d["files"], validate.SIGNATURE_NAME: "0" * 64}})
        self.assertRejects(pkg, f"不得列出 {validate.SIGNATURE_NAME}")


class RobustnessRules(PackageCase):
    """异常输入必须被报告为错误，而不是让校验器抛出异常（规范 8.3 要求目录用校验器自动检查所有发布的插件）。"""

    def assertReportsWithoutCrash(self, pkg: Path, fragment: str):
        try:
            errors = self.errors(pkg)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"校验器崩溃：{type(exc).__name__}: {exc}")
        self.assertIn(fragment, errors)

    def test_non_utf8_lecture(self):
        pkg = self.copy("intro-cs-content")
        (pkg / "content/lectures/variables.md").write_bytes("变量".encode("gbk"))
        self.assertReportsWithoutCrash(pkg, "不是 UTF-8 编码的文本")

    def test_non_utf8_renderer_entry(self):
        pkg = self.copy("flashcard-renderer")
        (pkg / "renderer/index.html").write_bytes("<p>闪卡</p>".encode("gbk"))
        self.assertReportsWithoutCrash(pkg, "不是 UTF-8 编码的文本")

    def test_non_utf8_manifest(self):
        pkg = self.copy("glossary-tool")
        (pkg / validate.MANIFEST_NAME).write_bytes('{"id": "术语"}'.encode("gbk"))
        self.assertReportsWithoutCrash(pkg, "不是 UTF-8 编码的文本")

    def test_content_pack_path_is_directory(self):
        pkg = self.copy("intro-cs-content")
        (pkg / "content/dir.json").mkdir()
        self.edit_json(pkg / validate.MANIFEST_NAME,
                       lambda m: m["contributes"]["contentPacks"][0].update(path="content/dir.json"))
        self.assertReportsWithoutCrash(pkg, "不是普通文件")

    def test_lecture_path_is_directory(self):
        pkg = self.copy("intro-cs-content")
        (pkg / "content/lectures/dir.md").mkdir()
        self.edit_json(pkg / "content/lectures.json",
                       lambda d: d["lectures"][0].update(path="content/lectures/dir.md"))
        self.assertReportsWithoutCrash(pkg, "不是普通文件")

    def test_cli_survives_internal_error(self):
        """单个包触发意外错误时，命令行计为失败并继续检查其他包。"""
        original = validate.check_package
        calls = []

        def flaky(package, validators):
            calls.append(package.name)
            if package.name == "boom":
                raise RuntimeError("模拟的意外错误")
            return original(package, validators)

        boom = Path(self.tmp.name) / "boom"
        boom.mkdir()
        validate.check_package = flaky
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = validate.main([str(boom), str(EXAMPLES / "glossary-tool")])
        finally:
            validate.check_package = original
        self.assertEqual(code, 1)
        self.assertEqual(calls, ["boom", "glossary-tool"])
        self.assertIn("校验器内部错误", out.getvalue())


def spec_text(name: str) -> str:
    return (validate.ROOT / "spec" / name).read_text(encoding="utf-8")


def json_block_after(text: str, heading: str):
    """取某个标题之后的第一个 ```json 代码块。"""
    match = re.search(re.escape(heading) + r".*?```json\n(.*?)```", text, re.S)
    assert match, f"找不到 {heading} 之后的 JSON 示例"
    return json.loads(match.group(1))


class DocumentExamples(PackageCase):
    def test_manifest_overview_example_is_valid(self):
        """第 01 章 1.2 的示例清单本身必须通过校验，且没有警告。"""
        manifest = json_block_after(spec_text("01-包与清单.md"), "## 1.2")
        pkg = Path(self.tmp.name) / "doc-example"
        pkg.mkdir()
        (pkg / validate.MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        # 为示例引用的文件放置最小桩文件
        (pkg / manifest["icon"]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
        entry = pkg / manifest["runtime"]["entry"]
        entry.parent.mkdir(parents=True)
        entry.write_text("", encoding="utf-8")
        for obj in manifest["contributes"].get("objectTypes", []):
            schema = pkg / obj["schema"]
            schema.parent.mkdir(parents=True, exist_ok=True)
            schema.write_text(json.dumps({"type": "object", "properties": {}, "additionalProperties": False}), encoding="utf-8")
        report = validate.check_package(pkg, VALIDATORS)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_integrity_example_matches_schema(self):
        """第 01 章 1.6 的完整性文件示例必须符合 integrity.schema.json。"""
        example = json_block_after(spec_text("01-包与清单.md"), "## 1.6")
        self.assertEqual(validate.schema_errors(VALIDATORS["integrity.schema.json"], example), [])

    def test_revocation_list_example_and_rules(self):
        """第 08 章 8.5 的吊销清单示例必须合规，且 Schema 能拦住不合规的写法。"""
        validator = VALIDATORS["revocation-list.schema.json"]
        example = json_block_after(spec_text("08-安全与审核.md"), "## 8.5")
        self.assertEqual(validate.schema_errors(validator, example), [])
        entry = example["entries"][0]
        invalid = {
            "* 与具体版本同时出现": {**entry, "versions": ["*", "1.0.0"]},
            "版本范围表达式": {**entry, "versions": [">=1.0.0"]},
            "未定义的严重程度": {**entry, "severity": "urgent"},
            "缺少原因": {k: v for k, v in entry.items() if k != "reason"},
            "空版本列表": {**entry, "versions": []},
        }
        for name, bad in invalid.items():
            with self.subTest(name):
                self.assertNotEqual(validate.schema_errors(validator, {**example, "entries": [bad]}), [])


class ProtocolSchemaConsistency(unittest.TestCase):
    TOOL_ID = "https://mentorbit.invalid/spec/0.1/tool-messages.schema.json"
    RENDERER_ID = "https://mentorbit.invalid/spec/0.1/renderer-messages.schema.json"

    def defs_validator(self, name: str, schema_id: str = TOOL_ID):
        return validate.Draft202012Validator({"$ref": f"{schema_id}#/$defs/{name}"}, registry=REGISTRY)

    @staticmethod
    def def_name(method: str, kind: str) -> str:
        """规范 4.5 / 5.4：去掉 host/ 前缀，按 / 与 . 分段驼峰拼接，再加 Params 或 Result。"""
        parts = re.split(r"[/.]", method.removeprefix("host/"))
        return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:]) + kind

    def test_every_renderer_method_has_schema_definitions(self):
        """第 04 章方法表中的请求必须有 Params 与 Result，通知只有 Params。"""
        rows = re.findall(r"^\| `([a-z]+/[A-Za-z]+)` \| (请求|通知) \|", spec_text("04-渲染器.md"), re.M)
        self.assertEqual(len(rows), 10)
        defs = SCHEMAS["renderer-messages.schema.json"]["$defs"]
        for method, kind in rows:
            with self.subTest(method=method):
                self.assertIn(self.def_name(method, "Params"), defs)
                if kind == "请求":
                    self.assertIn(self.def_name(method, "Result"), defs)
                else:
                    self.assertNotIn(self.def_name(method, "Result"), defs)

    def test_renderer_method_samples(self):
        cases = [
            ("stateGetResult", {"value": None}, True),
            ("stateGetResult", {}, False),
            ("uiSuggestPromptParams", {"text": "x" * 500}, True),
            ("uiSuggestPromptParams", {"text": "x" * 501}, False),
            ("uiOpenLinkParams", {"url": "http://example.com"}, False),
            ("renderDisposeParams", {}, True),
            ("uiReadyParams", {"protocol": "mentorbit.renderer/0.1"}, True),
        ]
        for name, sample, ok in cases:
            with self.subTest(name=name, sample=sample):
                self.assertEqual(self.defs_validator(name, self.RENDERER_ID).is_valid(sample), ok)

    def test_every_host_method_in_spec_has_schema_definitions(self):
        methods = re.findall(r"^\| `(host/[a-z.]+)` \|", spec_text("05-对象与工具.md"), re.M)
        self.assertIn("host/evidence.propose", methods)
        defs = SCHEMAS["tool-messages.schema.json"]["$defs"]
        for method in methods:
            for kind in ("Params", "Result"):
                with self.subTest(method=method, kind=kind):
                    self.assertIn(self.def_name(method, kind), defs)

    def test_learner_projection_example_matches_schema(self):
        """第 06 章 6.2 的投影示例必须符合 learnerReadResult。"""
        example = json_block_after(spec_text("06-学习数据与证据.md"), "## 6.2")
        errors = [e.message for e in self.defs_validator("learnerReadResult").iter_errors(example)]
        self.assertEqual(errors, [])

    def test_host_method_samples(self):
        valid = {
            "modelInvokeParams": {"callId": "c1", "messages": [{"role": "user", "content": "hi"}], "maxTokens": 64},
            "httpFetchParams": {"callId": "c1", "url": "https://api.example.com/x", "method": "GET"},
            "evidenceProposeParams": {"callId": "c1", "eventType": "practice.attempt_submitted", "payload": {}, "idempotencyKey": "k1"},
            "evidenceProposeResult": {"status": "duplicate"},
            "storageDeleteParams": {"callId": "c1", "key": "recent"},
        }
        invalid = {
            "httpFetchParams": {"callId": "c1", "url": "http://api.example.com/x", "method": "GET"},
            "learnerReadParams": {"callId": "c1", "dimension": "mood"},
            "evidenceProposeParams": {"callId": "c1", "eventType": "nodot", "payload": {}, "idempotencyKey": "k1"},
            "modelInvokeParams": {"callId": "c1", "messages": [], "maxTokens": 64},
        }
        for name, sample in valid.items():
            with self.subTest(valid=name):
                self.assertTrue(self.defs_validator(name).is_valid(sample))
        for name, sample in invalid.items():
            with self.subTest(invalid=name):
                self.assertFalse(self.defs_validator(name).is_valid(sample))


class PermissionTierConsistency(unittest.TestCase):
    # 第 02 章表格中带占位符的权限，用一个具体值代入后交给校验器判断
    CONCRETE = {
        "network:<origin>": "network:https://api.example.com",
        "objects.read:<插件 ID>/<对象类型>": "objects.read:example.glossary/glossary_entry",
        "learner.read:<维度>": "learner.read:knowledge",
        "evidence.propose:<事件类型>": "evidence.propose:practice.attempt_submitted",
    }

    def test_validator_tiers_match_permission_table(self):
        """校验器的最低信任等级规则必须与第 02 章 2.2 的权限表一致。"""
        rows = re.findall(r"^\| `([^`]+)` \| [^|]+\| `(community|verified|official)` \|", spec_text("02-权限与信任.md"), re.M)
        self.assertEqual(len(rows), 8)
        for permission, tier in rows:
            with self.subTest(permission=permission):
                self.assertEqual(validate.permission_min_tier(self.CONCRETE.get(permission, permission)), tier)


class ExampleSamples(unittest.TestCase):
    def test_sample_objects_match_declared_schemas(self):
        """examples/*/samples/ 下的样例对象必须符合其插件声明的对象类型 Schema。"""
        samples = sorted(EXAMPLES.glob("*/samples/*.json"))
        self.assertTrue(samples, "没有找到任何样例对象")
        for path in samples:
            with self.subTest(sample=path.relative_to(EXAMPLES).as_posix()):
                package = path.parent.parent
                manifest = json.loads((package / validate.MANIFEST_NAME).read_text(encoding="utf-8"))
                sample = json.loads(path.read_text(encoding="utf-8"))
                declared = {o["id"]: o for o in manifest["contributes"].get("objectTypes", [])}
                self.assertIn(sample["objectType"], declared)
                schema = json.loads((package / declared[sample["objectType"]]["schema"]).read_text(encoding="utf-8"))
                errors = [e.message for e in validate.Draft202012Validator(schema).iter_errors(sample["value"])]
                self.assertEqual(errors, [])
                self.assertTrue(1 <= len(sample["fallbackText"]) <= 2000)
                self.assertLessEqual(len(json.dumps(sample["value"], ensure_ascii=False).encode("utf-8")), 128 * 1024)


if __name__ == "__main__":
    unittest.main()
