"""校验工具的反例测试：每个用例在示例包的副本上制造一处违规，确认 validate.py 能报出来。

用法：python -m unittest tools/test_validate.py
"""

from __future__ import annotations

import hashlib
import json
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
        target = Path(self.tmp.name) / example
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


if __name__ == "__main__":
    unittest.main()
