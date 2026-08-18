# AGENTS.md

本文件给在本仓库工作的实现 bot / 验收 bot 的硬规则。  
一次只实现一个已冻结节点。当前节点是 6.2：Outline Revision（仅 Fake / 内存仓库）。不要启动节点 7.x。不要批准或提交 Canon。不要加入自动批准。不要调用任何真实模型 API。不要加入章级或全书级生成入口。不要加入向量检索。

开始任何任务前：先读 `docs/mvp-scope.md`、`docs/domain-glossary.md`、`docs/state-machines.md`、`docs/architecture.md` 与 `contracts/`。  
不要把未实现行为写成已完成。不要发明已落地的鉴权、队列、真实模型调用或生成器。节点 6.2 只做 Outline Revision。确认可用不是批准，不写 Canon。大纲不是生成单位。

## 已冻结、默认不可改

- `docs/mvp-scope.md`
- `docs/domain-glossary.md`
- `docs/state-machines.md`
- `contracts/` 下已存在的已批准 Schema、样例与测试（节点 0.4）

## MVP 前提（不是本节点新发明的行为）

与 0.1 / 0.2 / 0.3 对齐，下列为正常前提；相反项不是 MVP 正常行为：

- 一个故事项目、一名用户（创作者兼主编）、仅中文、一个写作模型供应商、生成单位为场景、必须人类批准。
- 自动批准不是 MVP 正常行为。
- 多项目不是 MVP 正常行为。
- Canon 高于散文。只有人类主编批准并提交后才能改 Canon。

## 八条规则

1. 每次只处理一个任务 ID。
2. 先读 docs 与 contracts。
3. 不修改已批准 Schema，除非显式提出迁移方案。
4. 不得记录 API 密钥、正文敏感内容或模型输出到 Git。
5. 每项功能必须有测试。
6. 修改数据库必须有迁移。
7. 运行格式化、类型检查、测试后才能结束。
8. 输出变更摘要、执行命令、测试结果、风险项。

## 命令示例（节点 1.2）

包管理只用 venv（`python3 -m venv` + `pip`）。不要加入 Poetry 或 uv。

```bash
python3 -m venv .venv
source .venv/bin/activate
make install
make format
make lint
make typecheck
make test
docker compose up -d postgres
uvicorn slove_context.app:app --app-dir backend --host 127.0.0.1 --port 8000
```

`make test` 用进程内 TestClient 检查 `/healthz`，不需要 Docker，不调用外部模型。

## 命令示例（节点 1.3）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏；不连 Postgres，不调用外部模型。`make migrate` 需要本地 Postgres，只建 `audit_events`。

## 节点 1.3 边界

- 每个 HTTP 请求有 `request_id`（接受或生成 `X-Request-ID`）。
- JSON 结构化日志（至少 request-complete：`timestamp`、`level`、`request_id`、`operation`、`duration_ms`）。
- Alembic 迁移：仅 `audit_events`（字段见 `docs/audit.md`）。
- 通用审计写入接口 + 默认脱敏（正文 / Prompt / 密钥）。单元测试用内存 sink。
- 保留 `GET /healthz` 与 `GET /version`。
- **不是** Canon 表或 Canon 写入路径、用户鉴权、队列、模型调用。
- **不是** 节点 2.1 的 Story Project / Story Spec。

## 命令示例（节点 2.1）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Story Spec API（schema 校验失败、未批准不得当作已批准、已批准禁止就地 PATCH）；不连 Postgres，不调用外部模型。`make migrate` 需要本地 Postgres，建 `audit_events`、`story_projects`、`story_specs`、`story_spec_versions`。不建 Canon 表。

## 节点 2.1 边界

- Story Project / Story Spec / Revision 持久化与 API。
- 仅一个故事项目：创建第二个项目被拒绝。
- 仅人工主编可批准 Spec（系统 / 生成 Agent / 审校 Agent 不可）。无自动批准路径。
- Spec 批准不是 Canon 批准；本节点不写 Canon。
- 已批准 Spec 不得就地 PATCH；改动必须出新的草稿 Revision。
- 载荷对照 `contracts/story-spec.schema.json`（Draft 2020-12）；非法输入 422。
- 写操作走既有 `AuditWriter`（1.3），沿用默认脱敏。
- 保留 `GET /healthz`、`GET /version`、`/openapi.json` 与 `audit_events`。
- **不是** Canon 实体 / 事实表（节点 2.2）。
- **不是** 角色、场景、模型调用、前端。

## 命令示例（节点 2.2）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、以及 Canon 实体 / 证据 / 事实（创建为 NotInCanon、仅人工主编批准或废弃、按项目 / 实体 / 谓语 / 故事时间查询生效事实、supersede 不得就地改写）；不连 Postgres，不调用外部模型。`make migrate` 需要本地 Postgres，建 `audit_events`、Story Project / Spec 表，以及 `entities`、`evidence_records`、`canon_facts`、`canon_fact_versions`、`canon_snapshots`。

## 节点 2.2 边界

- 最小 Canon 数据模型与 API：通用实体、证据、Canon 事实、不可变事实版本。
- Canon Fact 只追加；更正只能 supersede（旧 Active → Superseded，新事实 Active + 新版本行）。禁止就地改 Active 事实的正文 / value_json。
- 每条事实含 predicate、value_json、effective_story_time、valid_from_scene_id、status、source_type、evidence_id。
- 可按项目、实体、谓语、故事时间查询「当时生效」的 Active 事实。
- 创建 / 批准 / 废弃写既有 `AuditWriter`。仅人工主编可批准、废弃或 supersede（`X-Actor-Type: human_editor`）。无自动批准。
- `canon_snapshots` 只建表。不实现冻结作业或回放接口（节点 2.3）。
- 保留 `GET /healthz`、`GET /version`、`audit_events` 与节点 2.1 Story Project / Spec API。
- **不是** 向量检索、图数据库、自动抽取、LLM / 模型调用。
- **不是** 把角色 / 场景做成小说写作产品（实体只是通用对象）。
- **不是** 节点 2.3 的快照冻结 / 回放。

## 命令示例（节点 2.3）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon 事实 API，以及 Canon Snapshot（创建、仅人工主编冻结、按 snapshot_id 查询、稳定排序 diff、回放、后期新事实不得泄漏进更早快照）；不连 Postgres，不调用外部模型。`make migrate` 需要本地 Postgres，在 2.2 的 `canon_snapshots` 上增量加 `fact_ids`、`frozen_at`、`as_of_scene_seq`、`as_of_story_time`、`status`。不重建 Canon 表，不建 Scene Card / Context Pack 表。

## 节点 2.3 边界

- Canon Snapshot 创建、冻结、按 snapshot_id 查询可见事实、两快照 diff、回放查询。
- 快照是某时刻只读副本，不代替当前 Canon。按 snapshot_id 的查询只看该快照捕获的事实，不看 live Canon。
- 已冻结快照只读：事实列表不得再改。仅人工主编可冻结（`X-Actor-Type: human_editor`）。系统 / 生成 Agent / 审校 Agent 不可。无自动批准。
- Diff 输出稳定排序（fact id，然后 predicate）：added / removed / superseded。
- 回放：`snapshot_id` 加 `scene_id` 或 `as_of_story_time`，只返回该快照内当时应可见的 Canon。后期新批准事实不得泄漏进更早快照。
- 写操作走既有 `AuditWriter`（1.3），沿用默认脱敏。
- 保留 `GET /healthz`、`GET /version`、`audit_events`、节点 2.1 Story Project / Spec API、节点 2.2 Canon Fact API（live `GET /canon-facts` 仍是当前 Canon）。
- **不是** Scene Card（节点 3.1）、Context Pack、生成器、向量检索、LLM / 模型调用。

## 命令示例（节点 3.1）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon 事实与 Snapshot API，以及 Scene Card / 顺序 / 依赖（schema 校验失败、依赖未齐不得进入可生成、环依赖拒绝、故事顺序冲突、仅人工主编批准）；不连 Postgres，不调用外部模型。`make migrate` 需要本地 Postgres，建 `arcs`、`chapters`、`scenes`、`scene_dependencies`。不重建 Canon / 项目表，不建 Scene Plan / Scene Draft / 模型网关表。

## 节点 3.1 边界

- 最小 Scene Card 数据模型与 API：卷或弧 / 章为结构容器，场景为唯一生成单位。
- Scene Card 载荷对照 `contracts/scene-card.schema.json`（Draft 2020-12）；非法输入 422。
- 每场记录故事内顺序、POV、时间、地点、在场实体、起始状态、目标、冲突、预期结束状态、禁止事项。
- 可生成是派生标志：场景卡已批准（或已发表）且全部依赖场景已批准或已发表。依赖未齐不得进入可生成。
- 依赖图禁止成环；同一项目内故事顺序不得重复；场景不得排在其依赖之前。
- 创建 / 改草稿 / 批准 / 设依赖写既有 `AuditWriter`。仅人工主编可批准（`X-Actor-Type: human_editor`）。无自动批准。
- 批准 Scene Card 不是 Canon 批准，不写 Canon。
- 保留 `GET /healthz`、`GET /version`、`audit_events`、节点 2.1 Story Project / Spec API、节点 2.2 Canon Fact API、节点 2.3 Snapshot / 回放 API。
- **不是** 模型网关（节点 3.2）、Scene Plan / Scene Draft 生成、Context Pack、向量检索、LLM / 模型调用。
- **不是** 「生成一整章」入口。

## 命令示例（节点 3.2）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon 事实与 Snapshot API、Scene Card / 顺序 / 依赖，以及 LLM Gateway（Fake Provider 夹具、超时、重试耗尽、结构化解析失败、日志脱敏）。不连 Postgres，不调用外部模型，无网络。`make migrate` 需要本地 Postgres；本节点不新建表、不建 Scene Plan / Scene Draft / Context Pack 表。

## 节点 3.2 边界

- 可替换 Provider 接口：`generate_text` 与 `generate_structured`。
- 请求含 model、system_prompt、user_prompt、temperature、max_tokens、correlation_id、task_type。
- 响应含 request_id、provider、model、prompt_version、usage（token / cost）、latency_ms、raw_response_reference（仅 id/ref）、parsed_output、error。
- v1 只实现 Fake Provider，返回测试夹具。禁止对 OpenAI / Anthropic 等发真实 HTTP。
- 请求超时、指数退避、可配置 max retries。只对无持久化副作用的幂等 generate_* 读取重试；禁止盲目重试非幂等写（persist / commit / approve / Canon 写 / 已写入 audit+state 的路径用 `invoke_once`，只跑一次）。
- 记录 cost / token 字段。日志不得保存完整 Prompt 或散文正文；复用 1.3 `audit.redact`（引用 id / `[REDACTED]`）。
- 网关不写 Canon，不自动批准，不生成 Scene Plan / Scene Draft。
- 保留 `GET /healthz`、`GET /version`、`audit_events`、节点 2.1–2.3 API、节点 3.1 Scene Card API。
- **不是** 节点 3.3 的 Scene Plan 生成作业、具体生成 Prompt、Context Pack、向量检索、真实模型供应商客户端。

## 命令示例（节点 3.3）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon 事实与 Snapshot API、Scene Card / 顺序 / 依赖、LLM Gateway，以及 Scene Plan 生成作业（Fake Provider：成功、非法 JSON、依赖未齐、schema 失败且至多一次 format repair）。不连 Postgres，不调用外部模型，无网络。`make migrate` 需要本地 Postgres，建 `scene_plan_jobs`、`scene_plans`。不重建 Canon / 项目 / Scene Card 表，不建 Scene Draft / Context Pack / 真实模型网关表。

## 节点 3.3 边界

- 输入：已批准且可生成的 Scene Card + 指定 Canon Snapshot。依赖未齐或未批准则拒绝。
- 输出：对照 `contracts/scene-plan.schema.json` 的 Scene Plan。非法结构化输出不得作为有效计划落库。
- Prompt 模板带版本号（`prompts/scene_plan.v1.md`）；要求 JSON；禁止散文 / 正文 / Scene Draft。
- schema 失败至多一次 format repair；仍失败则 job failed 并保留证据（request refs、raw_response_reference、校验错误）。
- API：触发作业、查询作业、读取当前 Scene Plan。写既有 `AuditWriter`，沿用 1.3 脱敏。
- 仅 Fake Provider + 夹具。禁止对 OpenAI / Anthropic 等发真实 HTTP。
- Scene Plan 不是 Canon，也不是 Scene Draft。作业不写 Canon。无自动批准。
- 生成单位为单个场景。无「生成一整章」入口。
- 保留 `GET /healthz`、`GET /version`、`audit_events`、节点 2.1–3.2 API。
- **不是** 节点 3.4 的 Scene Draft 生成、Context Pack 组装器、向量检索、真实模型供应商客户端。

## 命令示例（节点 3.4）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon 事实与 Snapshot API、Scene Card / 顺序 / 依赖、LLM Gateway、Scene Plan 作业，以及 Scene Draft 生成作业（Fake Provider：成功、失败、幂等、取消、修订版本、审计脱敏）。不连 Postgres，不调用外部模型，无网络。`make migrate` 需要本地 Postgres，建 `scene_draft_jobs`、`scene_drafts`。不重建 Canon / 项目 / Scene Card / Scene Plan 表，不建 Candidate Change / Context Pack 组装表。

## 节点 3.4 边界

- 输入：已批准且可生成的 Scene Card + 有效 Scene Plan + 指定 Canon Snapshot + 预冻结 Context Pack 引用（静态夹具；本节点没有 Context Pack 组装器）。
- 输出：不可变 Scene Draft 散文 + 生成元数据 + 输入版本引用 + 内容哈希。重试出新 Revision，不得覆盖旧行。
- 草稿至多 `Generated`（可供后续抽取），不得自动批准或发表，不写 Canon。
- Prompt 模板带版本号（`prompts/scene_draft.v1.md`）；只生成这一场散文；禁止写 Canon。
- 幂等：同一 `idempotency_key` 在 queued / running / succeeded 时返回原作业；成功后再生成须新 key（或省略）并出新 Revision；取消为终态且不删除；失败作业可再开新作业 / Revision。
- 仅 Fake Provider + 夹具。禁止对 OpenAI / Anthropic 等发真实 HTTP。
- 写既有 `AuditWriter`，沿用 1.3 脱敏（完整 Prompt / 散文不得入日志）。
- 生成单位为单个场景。无「生成一整章」入口。无自动事实抽取（节点 4.1）。
- 保留 `GET /healthz`、`GET /version`、`audit_events`、节点 2.1–3.3 API。
- **不是** 节点 4.1 的自动事实抽取、Candidate Change 作业、Context Pack 组装器、向量检索、真实模型供应商客户端。

## 命令示例（节点 4.1）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon 事实与 Snapshot API、Scene Card / 顺序 / 依赖、LLM Gateway、Scene Plan / Scene Draft 作业，以及 Candidate Change 抽取作业（Fake Provider：成功且绑定 Evidence、非法 JSON、schema 失败且至多一次 format repair、幂等、失败可重试、不写 Canon、无自动批准）。不连 Postgres，不调用外部模型，无网络。`make migrate` 需要本地 Postgres，建 `extract_jobs`、`candidate_changes`，并允许 Scene Draft 状态 `Extracted`。不重建 Canon / 项目 / Scene Card / Scene Plan / Scene Draft 表，不建 Validation Run / Context Pack 组装 / 真实模型网关表。

## 节点 4.1 边界

- 输入：已生成且不可变的 Scene Draft（状态至少 Generated）+ 所属 Scene / 项目。草稿缺失、未生成、可被覆盖或已替换则拒绝。
- 输出：对照 `contracts/candidate-change.schema.json` 的候选变更列表。每条必须绑定 Evidence（`evidence_quote` + `source_scene_id`）。非法结构化输出不得作为有效候选落库。
- 抽取单位为单个场景。草稿正文不可变；抽取只写候选，不得覆盖散文。成功时草稿状态至多 Generated → Extracted（只改状态）。
- 候选初始状态只能是 Extracted。不得自动设 Validating / Approved / Submitted / AwaitingVerdict。
- Prompt 模板带版本号（`prompts/extract_candidates.v1.md`）；要求 JSON 数组或对象；禁止写 Canon、禁止批准、禁止生成新散文。
- schema 失败至多一次 format repair；仍失败则 job failed 并保留证据（request refs、raw_response_reference、校验错误）。
- 幂等：同一 `idempotency_key` 在 queued / running / succeeded 时返回原作业；取消为终态且不删除；失败作业可再开新作业（追加抽取批次，不覆盖旧候选）。
- 仅 Fake Provider + 夹具。禁止对 OpenAI / Anthropic 等发真实 HTTP。
- 写既有 `AuditWriter`，沿用 1.3 脱敏（完整 Prompt / 散文不得入日志）。
- Candidate Change 不是 Canon Fact。作业不写 Canon。无 Validate、无人工批准 / 提交（4.2）、无 Scene / Chapter 摘要。
- 生成 / 抽取单位为单个场景。无「生成一整章」入口。
- 保留 `GET /healthz`、`GET /version`、`audit_events`、节点 2.1–3.4 API。
- **不是** 节点 4.2 的人工批准 / 提交、Validation Run（5.x）、Context Pack 组装器、向量检索、真实模型供应商客户端。

## 命令示例（节点 4.2）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon 事实与 Snapshot API、Scene Card / 顺序 / 依赖、LLM Gateway、Scene Plan / Scene Draft 作业、Candidate Change 抽取作业，以及 Candidate Change 人类批准 / 拒绝 / 提交（Fake / 内存：批准不写 Canon、提交才创建或 supersede、非人类 403、Extracted 不能批准、拒绝不写 Canon、二次提交拒绝且不双写）。不连 Postgres，不调用外部模型，无网络。`make migrate` 需要本地 Postgres，在 `candidate_changes` 上增量加批准裁决与提交事实引用列。不重建 Canon / 项目 / Scene Card / Scene Plan / Scene Draft / extract 表，不建 Validation Run / Context Pack 组装 / 摘要 / 真实模型网关表。

## 节点 4.2 边界

- 输入：已处于 AwaitingVerdict 的 Candidate Change（本节点不实现 Validate；测试可直接种入 AwaitingVerdict）。
- Approval Decision 对照 `contracts/approval-decision.schema.json`（Draft 2020-12）；`created_by` 必须是人工主编。
- Approve：仅 AwaitingVerdict → Approved。只记录裁决，**不写 Canon**。
- Reject：AwaitingVerdict 或 Approved（提交前）→ Rejected。不写 Canon。记录保留。
- Submit：仅 Approved → Submitted。此时才创建新 Canon Fact，或 supersede 已有 Active 事实（复用 2.2 只追加 / supersede；禁止就地改 Active）。本对象仍是已提交的候选，**不变成** Canon Fact。
- Extracted / Validating / FailedValidation / Failed / Rework / Cancelled 不得 Approve 或 Submit。
- 仅人工主编可批准与提交（`X-Actor-Type: human_editor`）。系统 / 生成 Agent / 审校 Agent / 模型 / bot 不可。无自动批准。Approved 不得自动变成 Submitted。
- 二次提交：拒绝（409），不幂等，不双写 Canon。
- 失败 / 取消 / 拒绝保留记录，不删除。
- 写既有 `AuditWriter`，沿用 1.3 脱敏（完整 Prompt / 散文不得入日志）。
- 仅 Fake Provider / 内存仓库。禁止对 OpenAI / Anthropic 等发真实 HTTP。
- 保留 `GET /healthz`、`GET /version`、`audit_events`、节点 2.1–4.1 API。
- **不是** 节点 4.3 当时尚未交付的 Scene / Chapter 摘要、Validation Run / Validate（5.x）、Context Pack 组装器、向量检索、真实模型供应商客户端。

## 命令示例（节点 4.3）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon 事实与 Snapshot API、Scene Card / 顺序 / 依赖、LLM Gateway、Scene Plan / Scene Draft 作业、Candidate Change 抽取与人类批准 / 提交，以及 Scene / Chapter 摘要作业（Fake Provider：场景摘要须基于已有草稿、章摘要由场景摘要汇总、修订不可变、幂等、失败可重试、取消不删除、不写 Canon、无整章散文生成入口）。不连 Postgres，不调用外部模型，无网络。`make migrate` 需要本地 Postgres，建 `summary_jobs`、`scene_summaries`、`chapter_summaries`。不重建 Canon / 项目 / Scene Card / Scene Plan / Scene Draft / extract 表，不建 Validation Run / Context Pack 组装 / 真实模型网关表。

## 节点 4.3 边界

- 输入（Scene Summary）：已有且不可变的 Scene Draft 修订版本（`draft_revision_id` + 内容哈希）。草稿缺失则拒绝。
- 输入（Chapter Summary）：该章内已有的 Scene Summary。由场景摘要汇总，不是一次生成整章散文。所需场景摘要缺失则拒绝。
- 输出：短摘要 + 元数据（content hash、来源修订、Prompt 版本、generated_at）。修订不可变；重试出新 Revision，不得覆盖旧行。
- Prompt 模板带版本号（`prompts/scene_summary.v1.md`、`prompts/chapter_summary.v1.md`）。仅 Fake Provider + 夹具。禁止对 OpenAI / Anthropic 等发真实 HTTP。
- 幂等：同一 `idempotency_key` 在 queued / running / succeeded 时返回原作业；取消为终态且不删除；失败作业可再开新作业 / Revision。
- 写既有 `AuditWriter`，沿用 1.3 脱敏（完整 Prompt / 散文不得入日志）。
- 摘要不是 Canon、不是 Scene Draft、不是 Candidate Change。作业不写 Canon。无自动批准。无 Validate（5.x）。无新的抽取 / 批准 / 提交路径。
- 生成单位为单个场景。无「生成一整章」入口。
- 保留 `GET /healthz`、`GET /version`、`audit_events`、节点 2.1–4.2 API。
- **不是** 节点 5.x 当时尚未交付的 Validate / Validation Run、Context Pack 组装器、向量检索、真实模型供应商客户端。

## 命令示例（节点 5.1）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon 事实与 Snapshot API、Scene Card / 顺序 / 依赖、LLM Gateway、Scene Plan / Scene Draft 作业、Candidate Change 抽取与人类批准 / 提交、Scene / Chapter 摘要，以及 Validation Run（Fake / 内存：Passed 只到 AwaitingVerdict、RuleFailed 阻断批准、ExecFailed、非 Extracted 拒绝、缺 Evidence / Spec 拒绝、不写 Canon、无自动批准）。不连 Postgres，不调用外部模型，无网络。`make migrate` 需要本地 Postgres，建 `validation_runs`、`validation_reports`（违规嵌入报告 JSON）。不重建 Canon / 项目 / Scene Card / Scene Plan / Scene Draft / extract / 摘要表，不建 Repair Task / Context Pack 组装 / 真实模型网关表。

## 节点 5.1 边界

- 输入：已处于 Extracted 且绑定 Evidence 的 Candidate Change + 当前 Canon（或指定 Snapshot）+ 已写定 / 生效的 Story Spec。候选非 Extracted、缺 Evidence、缺规格或缺所需 Canon / Snapshot 则拒绝开跑。
- 输出：对照 `contracts/validation-report.schema.json` 的 Validation Report。Passed 的 `violations` 必须为空；RuleFailed 至少一条完整 Violation（`rule_id`、`severity`、`entity_ids`、`source_evidence`、`canon_evidence`、`recommended_action`）。
- 作业状态与 0.3 对齐：Queued / Running / Passed / RuleFailed / ExecFailed / Cancelled（不实现 Retrying / Rework；Rework 会开 Repair Task）。
- 候选转换：Extracted → Validating → AwaitingVerdict（Passed）或 FailedValidation（RuleFailed）或 Failed（ExecFailed）。
- Passed **不得**自动 Approve / Submit，**不得**写 Canon。只让候选进入人类裁决。
- RuleFailed / ExecFailed 不得进入批准。草稿 / 候选与 Canon 冲突时 Canon 胜。
- 规则确定：对照 Active Canon / Story Spec（冲突、forbid-list）。禁止调用真实模型。
- 失败 / 取消保留记录，不删除。
- 写既有 `AuditWriter`，沿用 1.3 脱敏。
- 仅 Fake / 内存仓库。禁止对 OpenAI / Anthropic 等发真实 HTTP。
- 保留 `GET /healthz`、`GET /version`、`audit_events`、节点 2.1–4.3 API。
- **不是** 节点 5.2 当时尚未交付的 Repair Task、自动批准、Context Pack 组装器、向量检索、真实模型供应商客户端。

## 命令示例（节点 5.2）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon 事实与 Snapshot API、Scene Card / 顺序 / 依赖、LLM Gateway、Scene Plan / Scene Draft 作业、Candidate Change 抽取与人类批准 / 提交、Scene / Chapter 摘要、Validation Run，以及 Repair Task（Fake / 内存：仅 RuleFailed / Violation 可开立、完成后必须再跑 Validation Run、RecheckPassed 不是批准且不写 Canon、再校验失败阻断批准、取消不删除、HumanReject 拒绝且不写 Canon）。不连 Postgres，不调用外部模型，无网络。`make migrate` 需要本地 Postgres，建 `repair_tasks`。不重建 Canon / 项目 / Scene Card / Scene Plan / Scene Draft / extract / 摘要 / Validation Run 表，不建 Context Pack 组装 / 真实模型网关表。

## 节点 5.2 边界

- 输入：RuleFailed Validation Report / Violation。Passed、仅 ExecFailed、无 Violation 不得开立。
- 状态与 0.3 对齐：Opened / InProgress / Completed / Rechecking / RecheckPassed / Failed / Cancelled / Rework。
- `recommended_action` / `action` 仅允许：ReviseScenePlan / Regenerate / Reextract / HumanReject。
- Completed 之后必须启动一次 5.1 Validation Run（复用现有 Validation Run 服务），不得跳过再校验。Completed → Rechecking。
- RecheckPassed 只表示候选可经 5.1 进入 AwaitingVerdict。**不是批准**，**不写 Canon**。
- 再校验 RuleFailed / ExecFailed 不得进入批准。失败 / 取消保留记录，不删除。
- 可调用既有 3.3 / 3.4 / 4.1 作业做 ReviseScenePlan / Regenerate / Reextract。无整章散文生成入口。
- HumanReject：对 FailedValidation 候选记录拒绝且不写 Canon（4.2 拒绝要求 AwaitingVerdict）。无新抽取时再校验为 N/A，仍不得批准或写 Canon。
- 写既有 `AuditWriter`，沿用 1.3 脱敏。
- 仅 Fake Provider / 内存仓库。禁止对 OpenAI / Anthropic 等发真实 HTTP。
- 保留 `GET /healthz`、`GET /version`、`audit_events`、节点 2.1–5.1 API。
- **不是** 节点 6.x 当时尚未交付的 Outline / Context Pack 组装器、自动批准、向量检索、真实模型供应商客户端。

## 命令示例（节点 6.1）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon 事实与 Snapshot API、Scene Card / 顺序 / 依赖、LLM Gateway、Scene Plan / Scene Draft 作业、Candidate Change 抽取与人类批准 / 提交、Scene / Chapter 摘要、Validation Run、Repair Task，以及 Context Pack 组装（Generate / Validate、缺卡 / 规格 / 快照拒绝、不写 Canon、无章级包入口）。不连 Postgres，不调用外部模型，无网络。`make migrate` 需要本地 Postgres，建 `context_packs`。不重建 Canon / 项目 / Scene Card / Scene Plan / Scene Draft / extract / 摘要 / Validation Run / Repair Task 表，不建 Outline / 真实模型网关表。

## 节点 6.1 边界

- 输入：一场场景 + 已批准 Scene Card + 已写定 / 生效 Story Spec + Canon Snapshot。卡未批准、规格未写定、快照缺失或未冻结、场景缺失则拒绝开组。
- 输出：对照 `contracts/context-pack.schema.json` 的 Context Pack。`purpose` 仅 Generate / Validate。`canon_excerpts` 是指定 Snapshot 的只读摘录，不得写回 Canon。
- 生成单位为单个场景。无章级或全书级 Context Pack。
- 冻结后只读：再组装出新 Revision / 新 id，不得覆盖旧行。冻结 Context Pack 不是 Canon 批准。
- 确定性复制 / 过滤 Snapshot 事实 + Spec + Card。禁止调用真实模型。
- 失败 / 取消保留记录，不删除。不批准、不提交、不抽取候选。
- 写既有 `AuditWriter`，沿用 1.3 脱敏（完整 Prompt / 散文不得入日志）。
- 仅 Fake / 内存仓库。禁止对 OpenAI / Anthropic 等发真实 HTTP。
- 3.4 Scene Draft 仍接受静态夹具 `context_pack_id`，也接受组装器产出的已冻结包。
- 保留 `GET /healthz`、`GET /version`、`audit_events`、节点 2.1–5.2 API。
- **不是** 节点 6.2 的 Outline、自动批准、向量检索、真实模型供应商客户端。

## 命令示例（节点 6.2）

```bash
make test
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 覆盖 `/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon 事实与 Snapshot API、Scene Card / 顺序 / 依赖、LLM Gateway、Scene Plan / Scene Draft 作业、Candidate Change 抽取与人类批准 / 提交、Scene / Chapter 摘要、Validation Run、Repair Task、Context Pack 组装，以及 Outline Revision（拟定 / 提交确认 / 确认可用、确认不是 Canon 批准、已确认禁止就地改、无章级生成、失败 / 取消不删除）。不连 Postgres，不调用外部模型，无网络。`make migrate` 需要本地 Postgres，建 `outline_revisions`。不重建 Canon / 项目 / Scene Card / Scene Plan / Scene Draft / extract / 摘要 / Validation Run / Repair Task / Context Pack 表，不建章级生成 / 真实模型网关表。

## 节点 6.2 边界

- 输入：唯一故事项目上的大纲修订；层次为 Story → Arc/Volume → Chapter → Scene。场景节点引用已有 3.1 Scene，不重建 Scene Card，不启动生成作业。
- 状态与 0.3 对齐：Drafting / Proposed / Confirmed / Revising / Failed / Cancelled / Rework / Superseded。
- 仅人工主编可将 Proposed → Confirmed（`X-Actor-Type: human_editor`）。系统 / 生成 Agent / 审校 Agent 不可确认可用。
- 确认可用不是 Approval，不写 Canon。大纲不是生成单位。无「生成一整章」或全书级生成入口。
- 已确认版本不得就地 PATCH；结构改动必须出新 Revision / 新 id（Revising → Proposed → Confirmed）。旧 Confirmed 可变为 Superseded。
- 节点字段至少含 goal、conflict、turning_point、start_state、end_state、constraints。
- 失败 / 取消保留记录，不删除。
- 写既有 `AuditWriter`，沿用 1.3 脱敏（完整 Prompt / 散文不得入日志）。
- 仅 Fake / 内存仓库。禁止对 OpenAI / Anthropic 等发真实 HTTP。
- 保留 `GET /healthz`、`GET /version`、`audit_events`、节点 2.1–6.1 API。
- **不是** 节点 7.x、自动批准、向量检索、真实模型供应商客户端、章级或全书级生成。
