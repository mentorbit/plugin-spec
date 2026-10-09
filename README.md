# Mentorbit 插件规范

**版本** 0.1.0-draft · **状态** 草案 · **许可** CC BY 4.0（正文）/ Apache-2.0（代码）

本规范定义 Mentorbit（星轨学伴）插件与宿主之间的契约，涵盖插件打包、权限、运行协议、学习数据访问与版本演进。规范性用语遵循 RFC 2119，见[第 00 章](spec/00-概述与约定.md#04-规范性用语)。

> 1.0 发布前，任何次版本均可能引入不兼容变更。Schema 的 `$id` 暂用保留域名 `mentorbit.invalid`。

## 设计范围

Mentorbit 由固定的内核与有限的扩展点组成。0.1 开放三类扩展点：**内容包**、**渲染器**、**工具**。身份与归属、权限与审批、会话日志、学习者状态与证据归约、插件宿主属于内核，不可由插件替换。

## 规范文档

| 章节 | 范围 | 状态 |
|---|---|---|
| [00 概述与约定](spec/00-概述与约定.md) | 术语、规范性用语、合规对象 | 草案 |
| [01 包与清单](spec/01-包与清单.md) | 包结构、清单字段、完整性 | 草案 |
| [02 权限与信任](spec/02-权限与信任.md) | 权限目录、授权流程、信任等级 | 草案 |
| [03 内容包](spec/03-内容包.md) | 课程图、题库、讲义 | 草案 |
| [04 渲染器](spec/04-渲染器.md) | iframe 沙箱、消息协议 | 草案 |
| [05 对象与工具](spec/05-对象与工具.md) | 对象信封、工具声明、进程协议 | 草案 |
| [06 学习数据与证据](spec/06-学习数据与证据.md) | 数据读取、证据提议、禁止行为 | 草案；证据提议为实验性 |
| [07 版本与演进](spec/07-版本与演进.md) | 版本策略、状态标签、变更流程 | 草案 |
| [08 安全与审核](spec/08-安全与审核.md) | 不可信输出、供应链、审核、吊销 | 草案 |
| [附录 A](spec/附录A-开放问题.md) | 待决事项 | — |
| [附录 B](spec/附录B-数值上限.md) | 各字段的长度、数量与取值上限，由 Schema 生成 | 草案 |

状态标签的定义见 [7.4](spec/07-版本与演进.md#74-状态标签)。规范由正文、附录 B 与 [`schemas/`](schemas/)（JSON Schema 2020-12）共同组成，冲突时的优先级见 [0.7](spec/00-概述与约定.md#07-规范的组成与优先级)。

## 仓库结构

```text
spec/       规范正文
schemas/    JSON Schema
examples/   示例插件：内容包、渲染器、工具
tools/      校验器、冒烟测试宿主、渲染器开发宿主、附录 B 生成器
.github/    持续集成（Windows、Linux、macOS）与依赖自动更新
```

## 校验

运行本仓库的工具需要 Python 3.10 及以上版本。这与插件运行环境的版本要求无关，后者见 [1.5](spec/01-包与清单.md#15-运行时)。

Windows（PowerShell）：

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r tools/requirements.txt
.venv\Scripts\python tools/validate.py examples/intro-cs-content examples/flashcard-renderer examples/glossary-tool
.venv\Scripts\python tools/smoke_tool.py examples/glossary-tool
.venv\Scripts\python -m unittest discover -s tools -p "test_*.py"
```

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r tools/requirements.txt
.venv/bin/python tools/validate.py examples/intro-cs-content examples/flashcard-renderer examples/glossary-tool
.venv/bin/python tools/smoke_tool.py examples/glossary-tool
.venv/bin/python -m unittest discover -s tools -p "test_*.py"
```

| 工具 | 用途 |
|---|---|
| `tools/validate.py` | 校验插件包：清单、权限、路径、引用完整性、对象 Schema、渲染器入口、受限 Markdown、完整性文件 |
| `tools/smoke_tool.py` | 按第 05 章协议运行工具插件，检查握手、回调、并发、取消、超时、权限撤销、大小上限、畸形消息与关闭；目前只支持 `python3` 插件 |
| `tools/renderer_host/serve.py` | 渲染器开发宿主，按第 04 章要求加载渲染器，默认监听 `http://127.0.0.1:8765/` |
| `tools/gen_limits.py` | 根据 Schema 生成附录 B；`--check` 只检查是否一致 |
| `tools/test_*.py` | 单元测试：校验器反例与模糊测试、冒烟宿主、渲染器开发宿主，以及正文、示例与 Schema 的一致性 |

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。规范变更遵循 [7.5 变更流程](spec/07-版本与演进.md#75-变更流程)；推送与合并请求会在 GitHub Actions 上于 Windows、Linux、macOS 运行全部检查。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

## 许可

Copyright © 2026 The Mentorbit Authors（Mentorbit 项目作者，以 Git 提交记录为准）

| 范围 | 许可 |
|---|---|
| `spec/` 下的规范正文、`README.md` 及其他说明文档 | CC BY 4.0，全文见 [LICENSE-CC-BY](LICENSE-CC-BY) |
| `schemas/`、`tools/`、`examples/`、`.github/` 下的全部文件 | Apache-2.0，全文见 [LICENSE-APACHE](LICENSE-APACHE) |

依据本规范实现宿主或插件，不需要采用上述任一许可；插件可以闭源发布。
