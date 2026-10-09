# 参与贡献

## 提出变更

- 讨论与提案请提交议题。规范性变更遵循 [7.5 变更流程](spec/07-版本与演进.md#75-变更流程)：在同一次修改中同步更新正文、`schemas/`、校验工具、示例与测试，并公示至少 14 天。
- 规范正文中的规范性要求使用加粗的“必须 / 不得 / 应当 / 不应 / 可以”（见 [0.4](spec/00-概述与约定.md#04-规范性用语)）；描述性文字请避免使用这些词，测试会检查。
- [附录 B](spec/附录B-数值上限.md) 由 `tools/gen_limits.py` 根据 `schemas/` 生成，修改上限时先改 Schema，再重新生成，不要手工编辑。

## 本地检查

提交前请运行 README 中“校验”一节的全部命令，并重新生成附录 B：

```powershell
.venv\Scripts\python tools/gen_limits.py
```

推送与合并请求会在 GitHub Actions 上于 Windows、Linux、macOS 运行同样的检查。

## 提交内容

- 提交信息使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式，例如 `fix: 修正某某规则`。
- 不要提交个人信息、凭据、本机路径或日志；示例内容须为原创或可再分发，并在 `attribution` 中注明来源。
- 安全问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要公开提交议题。

提交贡献即表示同意按 README 中的许可发布：规范正文采用 CC BY 4.0，Schema、工具与示例代码采用 Apache-2.0。
