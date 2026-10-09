# 变更记录

## 0.1.0-draft（未发布）

首个草案。

- 定义清单、权限与信任等级、内容包（课程图、题库、讲义）、渲染器沙箱与消息协议、对象信封、工具声明与隔离进程运行协议、学习数据与证据原则、版本与变更流程、安全与审核要求，以及完整性文件（1.6）与吊销清单（8.5）的格式。
- 提供 JSON Schema（含工具协议与渲染器协议全部方法的参数与结果定义，命名规则见 4.5、5.4；完整性文件与吊销清单各有独立 Schema）与三个示例插件。
- 附录 B 汇总全部数值上限，由 `tools/gen_limits.py` 根据 Schema 生成。
- 规范的组成与优先级见 0.7：数值上限以 Schema 为准，其余以正文为准。
- 提供工具：校验器 `tools/validate.py`（受限 Markdown 使用 CommonMark 解析器检查，支持数学公式）、工具冒烟宿主 `tools/smoke_tool.py`、渲染器开发宿主 `tools/renderer_host/`、附录 B 生成器 `tools/gen_limits.py`，以及单元测试 `tools/test_*.py`（含模糊测试，以及正文、示例与 Schema 的一致性检查）；持续集成在 Windows、Linux、macOS 上运行全部检查。
- 许可证全文为 `LICENSE-CC-BY`（规范正文）与 `LICENSE-APACHE`（Schema、工具与示例），版权与适用范围见 README。
- 工具运行环境为 `python3`（CPython 3.11+）与 `node`（Node.js 22+）；`native`、教学技能、轮次钩子、模型与搜索供应商、判题器扩展点保留到后续版本。
