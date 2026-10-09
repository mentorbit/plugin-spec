# 附录 B 数值上限

> 状态：草案

本附录由 `tools/gen_limits.py` 根据 `schemas/` 生成，汇总各数据结构的长度、数量与取值上限。数值上限以 Schema 为准（见 0.7）；修改上限时**必须**修改 Schema 并重新生成本附录（见 7.5）。

字段路径中，`[]` 表示数组元素，`#名称` 表示 Schema 内的共享定义，`<键>`、`<值>` 分别表示对象的键与值。

| Schema | 字段 | 约束 |
|---|---|---|
| `content/course-graph.schema.json` | `license` | 最短 1 个字符 |
| `content/course-graph.schema.json` | `attribution` | 最短 1 个字符，最长 1000 个字符 |
| `content/course-graph.schema.json` | `nodes` | 至少 1 项，至多 5000 项 |
| `content/course-graph.schema.json` | `nodes[].cluster` | 最短 1 个字符，最长 64 个字符 |
| `content/course-graph.schema.json` | `nodes[].tags` | 至多 16 项 |
| `content/course-graph.schema.json` | `nodes[].tags[]` | 最短 1 个字符，最长 32 个字符 |
| `content/course-graph.schema.json` | `nodes[].estimatedHours` | ≤ 2000，> 0 |
| `content/course-graph.schema.json` | `edges` | 至多 20000 项 |
| `content/course-graph.schema.json` | `#localizedText` | 最短 1 个字符 |
| `content/course-graph.schema.json` | `#localizedText` | 至少 1 个键 |
| `content/course-graph.schema.json` | `#localizedText.<值>` | 最短 1 个字符 |
| `content/course-graph.schema.json` | `#source.title` | 最短 1 个字符，最长 200 个字符 |
| `content/lecture-set.schema.json` | `license` | 最短 1 个字符 |
| `content/lecture-set.schema.json` | `attribution` | 最短 1 个字符，最长 1000 个字符 |
| `content/lecture-set.schema.json` | `lectures` | 至少 1 项，至多 2000 项 |
| `content/lecture-set.schema.json` | `lectures[].title` | 最短 1 个字符 |
| `content/lecture-set.schema.json` | `lectures[].title` | 至少 1 个键 |
| `content/lecture-set.schema.json` | `lectures[].title.<值>` | 最短 1 个字符 |
| `content/lecture-set.schema.json` | `lectures[].nodes` | 至少 1 项 |
| `content/lecture-set.schema.json` | `lectures[].estimatedMinutes` | ≥ 1，≤ 600 |
| `content/question-bank.schema.json` | `license` | 最短 1 个字符 |
| `content/question-bank.schema.json` | `attribution` | 最短 1 个字符，最长 1000 个字符 |
| `content/question-bank.schema.json` | `questions` | 至少 1 项，至多 10000 项 |
| `content/question-bank.schema.json` | `#markdown` | 最短 1 个字符，最长 20000 个字符 |
| `content/question-bank.schema.json` | `#question.options` | 至少 2 项，至多 10 项 |
| `content/question-bank.schema.json` | `#question.answer.optionIds` | 至少 1 项 |
| `content/question-bank.schema.json` | `#question.answer.rubric` | 至多 10 项 |
| `content/question-bank.schema.json` | `#question.answer.rubric[]` | 最短 1 个字符，最长 500 个字符 |
| `content/question-bank.schema.json` | `#question.hints` | 至多 5 项 |
| `content/question-bank.schema.json` | `#question.nodes` | 至少 1 项 |
| `content/question-bank.schema.json` | `#question.difficulty` | ≥ 1，≤ 5 |
| `content/question-bank.schema.json` | `#question.answer.optionIds` | 至多 1 项 |
| `integrity.schema.json` | `files` | 至少 1 个键，至多 5000 个键 |
| `manifest.schema.json` | `publisher.displayName` | 最短 1 个字符，最长 80 个字符 |
| `manifest.schema.json` | `license` | 最短 1 个字符，最长 200 个字符 |
| `manifest.schema.json` | `permissions` | 至多 32 项 |
| `manifest.schema.json` | `contributes.objectTypes` | 至多 64 项 |
| `manifest.schema.json` | `contributes.tools` | 至多 32 项 |
| `manifest.schema.json` | `contributes.renderers` | 至多 32 项 |
| `manifest.schema.json` | `contributes.contentPacks` | 至多 64 项 |
| `manifest.schema.json` | `contributes.tools` | 至少 1 项 |
| `manifest.schema.json` | `#httpsUrl` | 最长 2048 个字符 |
| `manifest.schema.json` | `#relPath` | 最短 1 个字符，最长 512 个字符 |
| `manifest.schema.json` | `#localizedText` | 最短 1 个字符 |
| `manifest.schema.json` | `#localizedText` | 至少 1 个键 |
| `manifest.schema.json` | `#localizedText.<值>` | 最短 1 个字符 |
| `manifest.schema.json` | `#permissionRequest.reason` | 最短 1 个字符，最长 120 个字符 |
| `manifest.schema.json` | `#toolContribution.description` | 最短 1 个字符，最长 1024 个字符 |
| `manifest.schema.json` | `#toolContribution.whenToUse` | 最短 1 个字符，最长 500 个字符 |
| `manifest.schema.json` | `#toolContribution.whenNotToUse` | 最短 1 个字符，最长 500 个字符 |
| `manifest.schema.json` | `#toolContribution.timeoutMs` | ≥ 100，≤ 120000 |
| `manifest.schema.json` | `#rendererContribution.objectTypes` | 至少 1 项 |
| `manifest.schema.json` | `#rendererContribution.minHeight` | ≥ 40，≤ 4000 |
| `manifest.schema.json` | `#rendererContribution.maxHeight` | ≥ 40，≤ 4000 |
| `object-envelope.schema.json` | `fallbackText` | 最短 1 个字符，最长 2000 个字符 |
| `renderer-messages.schema.json` | `#emptyObject` | 至多 0 个键 |
| `renderer-messages.schema.json` | `#stateKey` | 最短 1 个字符，最长 64 个字符 |
| `renderer-messages.schema.json` | `#uiResizeParams.height` | ≥ 0，≤ 10000 |
| `renderer-messages.schema.json` | `#uiSuggestPromptParams.text` | 最短 1 个字符，最长 500 个字符 |
| `renderer-messages.schema.json` | `#uiOpenLinkParams.url` | 最长 2048 个字符 |
| `revocation-list.schema.json` | `entries` | 至多 100000 项 |
| `revocation-list.schema.json` | `entries[].versions` | 至少 1 项 |
| `revocation-list.schema.json` | `entries[].reason` | 最短 1 个字符，最长 500 个字符 |
| `revocation-list.schema.json` | `entries[].versions` | 至多 1 项 |
| `tool-messages.schema.json` | `#id` | 最短 1 个字符，最长 64 个字符 |
| `tool-messages.schema.json` | `#request.method` | 最短 1 个字符 |
| `tool-messages.schema.json` | `#notification.method` | 最短 1 个字符 |
| `tool-messages.schema.json` | `#initializeParams.limits.maxConcurrentCalls` | ≥ 1 |
| `tool-messages.schema.json` | `#toolsCallParams.scope.learnerRef` | 最短 8 个字符，最长 128 个字符 |
| `tool-messages.schema.json` | `#toolsCallParams.scope.sessionRef` | 最短 8 个字符，最长 128 个字符 |
| `tool-messages.schema.json` | `#toolsCallParams.timeoutMs` | ≥ 1，≤ 120000 |
| `tool-messages.schema.json` | `#toolsCallResult.summary` | 最长 4000 个字符 |
| `tool-messages.schema.json` | `#toolsCallResult.objects` | 至多 16 项 |
| `tool-messages.schema.json` | `#toolsCallResult.objects[].fallbackText` | 最短 1 个字符，最长 2000 个字符 |
| `tool-messages.schema.json` | `#emptyObject` | 至多 0 个键 |
| `tool-messages.schema.json` | `#storageGetParams.key` | 最短 1 个字符，最长 64 个字符 |
| `tool-messages.schema.json` | `#storageSetParams.key` | 最短 1 个字符，最长 64 个字符 |
| `tool-messages.schema.json` | `#modelInvokeParams.messages` | 至少 1 项，至多 64 项 |
| `tool-messages.schema.json` | `#modelInvokeParams.messages[].content` | 最长 32000 个字符 |
| `tool-messages.schema.json` | `#modelInvokeParams.maxTokens` | ≥ 1，≤ 8192 |
| `tool-messages.schema.json` | `#httpFetchParams.url` | 最长 2048 个字符 |
| `tool-messages.schema.json` | `#httpFetchParams.body` | 最长 262144 个字符 |
| `tool-messages.schema.json` | `#httpFetchResult.status` | ≥ 100，≤ 599 |
| `tool-messages.schema.json` | `#httpFetchResult.body` | 最长 1048576 个字符 |
| `tool-messages.schema.json` | `#learnerReadResult.entries` | 至多 50 项 |
| `tool-messages.schema.json` | `#learnerReadResult.entries[].key` | 最短 1 个字符，最长 200 个字符 |
| `tool-messages.schema.json` | `#learnerReadResult.entries[].summary` | 最长 500 个字符 |
| `tool-messages.schema.json` | `#evidenceProposeParams.idempotencyKey` | 最短 1 个字符，最长 128 个字符 |
