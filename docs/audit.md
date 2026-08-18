# 审计与脱敏（节点 1.3）

本文只说明节点 1.3 已落地的审计写入接口与默认脱敏。  
不是鉴权、9.x 评测或真实模型客户端。节点 2.1 的 Story Project / Story Spec 写操作、节点 2.2 的实体 / 证据 / Canon 事实创建、批准与废弃、节点 2.3 的 Canon Snapshot 创建与冻结、节点 3.1 的 Scene Card 创建 / 改草稿 / 批准 / 设依赖、节点 3.2 LLM Gateway 在重试循环结束后的一次审计（若注入了 `AuditWriter`），节点 3.3 Scene Plan 作业的创建 / 状态转换 / 计划落库，节点 3.4 Scene Draft 作业的创建 / 状态转换 / 草稿落库，以及节点 4.1 Candidate Change 抽取作业的创建 / 状态转换 / 候选落库、节点 4.2 人类批准 / 拒绝 / 提交、节点 4.3 Scene / Chapter 摘要作业的创建 / 状态转换 / 摘要落库、节点 5.1 Validation Run 的创建 / 状态转换 / 报告落库、节点 5.2 Repair Task 的创建 / 状态转换、节点 6.1 Context Pack 组装 / 冻结 / 取消、节点 6.2 Outline Revision 的创建 / 拟定 / 确认 / 修订 / 取消、节点 7.1 Style Guide / Style Sample 的创建 / 批准 / 授权 / 修订 / 取消、节点 7.2 Style Validation 的创建 / 状态转换 / 报告落库、节点 7.3 审校队列入队 / 裁决、节点 8.1 作业入队 / 取消 / rerun / Worker 分发、节点 8.2 Agent 注册与 Agent Run、节点 8.3 单场景 DAG、节点 8.4 批量调度、节点 9.1 评测 runner、节点 9.2 实验运行，复用本接口。Spec 批准不是 Canon 批准。快照冻结不是 Canon 批准。批准 Scene Card 不是 Canon 批准，不写 Canon。生成 Scene Plan / Scene Draft / 抽取候选 / 写摘要不是 Canon 批准，不写 Canon。批准候选变更本身不写 Canon；只有人类提交才写 Canon。Gateway 不写 Canon。Context Pack 冻结不是 Canon 批准，不写 Canon。Outline 确认可用不是 Canon 批准，不写 Canon。批准 Style Guide / 授权 Style Sample 不是 Canon 批准，不写 Canon。Style Validation 不是 Canon 批准，不写 Canon，默认不阻断 Canon 提交。审校队列 approve 不是 Canon 提交；候选变更的队列 approve 只复用 4.2 裁决。批准 Style Report 不是 Canon 批准。Worker 分发不是批准，不写 Canon。Agent Run 不是 Canon 写入；Human Approver 批准不是 submit。证据正文与完整 Prompt 不得写入 `before_json` / `after_json`。Scene Draft 审计只存哈希与引用，不存完整散文。Candidate Change 审计不存 `evidence_quote` 原文。摘要审计只存哈希与来源修订引用，不存完整摘要或草稿正文。Validation Report 审计不存 `source_evidence` / `canon_evidence` 原文。Repair Task 审计不存违规原文或散文。Context Pack 审计不存 `scene_draft_excerpt` / `statement` / `source_evidence` 原文。Outline Revision 审计不存节点 goal / conflict / turning_point 原文。Style Guide / Sample 审计不存正例 / 反例 / 样本正文。Style Validation 审计不存草稿散文 / 正例 / 反例 / 样本正文 / `text_evidence` 原文。审校队列审计不存正文 / 正例 / 反例 / sample / `text_evidence`。作业队列审计只存 id / 状态 / payload_reference，不存完整 Prompt 或散文。Agent Run 审计只存 id / agent_id / input_ref / output_ref / 状态，不存完整 Prompt 或散文。Scene DAG / 批量调度审计只存 id / 状态 / 引用，不存完整 Prompt 或散文。调度器暂停与告警不是批准，不写 Canon。实验运行审计只存 id / 配置 / 输出引用 / 指标，不存完整 Prompt、散文或 `text_evidence`。实验不得批准或提交 Canon。

MVP 前提仍适用：一个故事项目、一名用户（创作者兼主编）、仅中文、必须人类批准。自动批准与多项目不是 MVP 正常行为。只有人类主编批准并提交后才能改 Canon。

## 1. 请求关联

- 每个 HTTP 请求都有 `request_id`。
- 若请求带 `X-Request-ID` 且非空，则沿用该值；否则服务端生成。
- 响应回传同一个 `X-Request-ID`。
- `/healthz` 与 `/version` 行为不变，只是多了该头。

实现：`backend/slove_context/middleware.py`。

## 2. 结构化日志

使用 Python `logging` + JSON formatter，不接入外部日志 SaaS。

每条 **request complete** 记录至少包含：

| 字段 | 含义 |
| --- | --- |
| `timestamp` | UTC ISO-8601 |
| `level` | 日志级别 |
| `request_id` | 本请求关联 id |
| `operation` | 如 `GET /healthz` |
| `duration_ms` | 处理耗时（毫秒） |

请求体、故事散文、模型 Prompt、API 密钥不得写入日志。见第 4 节。

实现：`backend/slove_context/logging.py`。

## 3. `audit_events` 表

Alembic 迁移（可在 PR 中直接审阅）：

`backend/alembic/versions/001_create_audit_events.py`

列（全部）：`id`、`occurred_at`、`actor_type`、`actor_id`、`action`、`resource_type`、`resource_id`、`before_json`、`after_json`、`correlation_id`。

本节点应用在进程内用 `AuditWriter` + `InMemoryAuditSink`（或其它 `AuditSink`）写事件。单元测试不连 Postgres。本地若要对真实库建表：

```bash
docker compose up -d postgres
cd backend && alembic upgrade head
```

FastAPI 本节点仍不打开数据库会话，也不写业务表。

## 4. 默认脱敏策略

`slove_context.audit.redact` 在写入 sink **之前**执行。策略：

| 类别 | 判定（键名，大小写不敏感；`-` 视为 `_`） | 落库 / 日志中的形态 |
| --- | --- | --- |
| 密钥 / key | `api_key`、`secret`、`password`、`token`、`authorization`、`model_api_key` 等；或以 `_key` / `_secret` / `_token` / `_password` / `_credential` 结尾 | 固定字符串 `[REDACTED]` |
| Prompt | `prompt`、`system_prompt`、`user_prompt`、`model_prompt` 等，或键名含 `prompt`（`prompt_version` / `prompt_tokens` 是版本号与计数，不是 Prompt 正文，不按正文脱敏） | 只存引用：`{"redacted": true, "kind": "prompt", "ref": "prompt:<sha256 前 16 位>"}` |
| 正文 / 散文 | `body`、`prose`、`scene_draft`、`story_body`、`evidence_quote`、`source_evidence`、`canon_evidence`、`positive_examples`、`negative_examples`、`sample_body`、`text_evidence`、`正例`、`反例` 等 | 只存引用：`{"redacted": true, "kind": "body", "ref": "body:<sha256 前 16 位>"}` |

嵌套 dict / list 会递归处理。引用 id 用于对照，不还原原文。

**禁止**：把原始 API 密钥、故事正文 / 散文、模型 Prompt 写入 Git、日志或 `audit_events.before_json` / `after_json`。

本节点不调用真实写作模型；测试里的密钥与正文都是占位，不是真实密钥或产品正文。节点 3.2 Fake Provider 的夹具同样是占位字符串，不是产品 Prompt 或散文。

节点 3.2 网关日志走 `slove_context.llm.redact.redact_llm`，内部调用本文件的 `audit.redact`。`raw_response_reference` 只记 id/ref，不记原始响应体。

## 5. 本节点明确不是

- 用户鉴权、真实模型客户端
- 自动批准、多项目
- 节点 8.3 及之后（DAG / 批量 / 评测）
