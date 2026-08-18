# slove-context
slove context

本地单机、一个故事项目、一名用户（创作者兼主编）、仅中文。候选变更须经人类主编批准或拒绝后才能提交 Canon。自动批准与多项目不是 MVP 正常行为。

节点 1.1 建立了本地单体仓库骨架。节点 1.2 在此基础上提供可运行的本地 Postgres 与 FastAPI `/healthz` / `/version`。节点 1.3 增加请求 `request_id`、JSON 结构化日志、以及 `audit_events` 迁移与通用审计写入接口。节点 2.1 增加唯一 Story Project 与 Story Spec 草稿 / 提交 / 人工批准 / 修订版本。节点 2.2 增加最小 Canon 实体 / 证据 / 事实 API（只追加，supersede 更正）。节点 2.3 增加 Canon Snapshot 创建、冻结、按 snapshot_id 查询、diff 与回放。节点 3.1 增加 Scene Card、故事内顺序与场景依赖（卷 / 章仅为结构容器）。节点 3.2 增加可替换 LLM Gateway 与仅 Fake Provider（夹具，无外部模型 HTTP）。节点 3.3 增加 Scene Plan 生成作业。节点 3.4 增加 Scene Draft 生成作业（不可变修订版本；仅 Fake Provider）。节点 4.1 增加 Candidate Change 抽取作业。节点 4.2 增加人类批准 / 拒绝 / 提交。节点 4.3 增加 Scene / Chapter 摘要作业（场景摘要基于已有草稿；章摘要由场景摘要汇总，不是整章散文生成）。节点 5.1 增加 Validation Run（确定性规则；Passed 只到 AwaitingVerdict，不写 Canon）。节点 5.2 增加 Repair Task（仅从 RuleFailed / Violation 开立；完成后必须再校验；RecheckPassed 不是批准，不写 Canon）。节点 6.1 增加 Context Pack 组装器（确定性；单场；Snapshot 摘录只读；冻结后不可变）。节点 6.2 增加 Outline Revision（拟定 → 提交确认 → 仅人工主编确认可用；确认不是批准，不写 Canon；已确认版本不可就地改）。本仓库没有用户鉴权、队列或真实模型调用。Spec 批准与 Scene Card 批准都不是 Canon 批准。快照不代替当前 Canon。大纲确认可用不是 Canon 批准。没有「生成一整章」或全书级散文入口。没有章级 Context Pack。

**包管理：只用 venv**（`python3 -m venv` + `pip`）。不要加入 Poetry 或 uv。

## 目录

| 路径 | 说明 |
| --- | --- |
| `AGENTS.md` | 实现约定（八条规则）与常用命令示例 |
| `docs/` | 已冻结范围 / 术语 / 状态机，骨架边界 `architecture.md`，以及 `audit.md` |
| `contracts/` | 已批准 JSON Schema（节点 0.4） |
| `backend/` | FastAPI 应用（`/healthz`、`/version`、2.1–9.3 API：含单场景 DAG、批量调度、实验运行与发布门 / 全书导出；无真实模型客户端）与 9.1 评测 runner |
| `backend/alembic/` | 可审阅迁移至 `023_release`（单元测试不连库） |
| `evals/` | 节点 9.1 叙事一致性评测案例 / 夹具 / 期望（确定性 runner，不写 Canon；9.2 只读引用） |
| `tests/` | 进程内测试（含 8.4 批量调度、9.1 评测、9.2 实验运行、9.3 发布门与 UI.1 Demo 播种）；`make test` 也会跑 contracts 测试 |
| `frontend/` | 节点 UI.1 本地工作流 Demo（Vite + React + TypeScript；Fake Provider；无登录） |
| `scripts/` | 脚本目录占位 |
| `data/` | 本地数据占位（不提交密钥或模型输出） |
| `docker-compose.yml` | 可启动的 Postgres（healthcheck + 持久卷） |
| `.env.example` | 环境变量名与安全注释（含 Postgres 占位） |

## 本地开始（节点 1.2 + 1.3 + 2.1 + 2.2 + 2.3 + 3.1 + 3.2 + 3.3 + 3.4 + 4.1 + 4.2 + 4.3 + 5.1 + 5.2 + 6.1 + 6.2）

只用 **venv**。复制 `.env.example` 为 `.env`。不要填入真实密钥，也不要把 `.env` 提交到 Git。

```bash
python3 -m venv .venv
source .venv/bin/activate
make install
```

### 启动 Postgres

```bash
docker compose up -d postgres
docker compose ps
```

等到 `postgres` 为 healthy。数据落在命名卷 `postgres_data`。`audit_events`、Story Project / Spec、Canon 表、snapshot 列、Scene / Scene Plan / Scene Draft / extract / summary 表用 Alembic 建（见下方「迁移」）；单元测试不跑迁移、不连库。`canon_snapshots` 在 2.2 建表，2.3 增量加冻结 / 回放列。节点 3.1 建 `arcs` / `chapters` / `scenes` / `scene_dependencies`。节点 3.3 建 `scene_plan_jobs` / `scene_plans`。节点 3.4 建 `scene_draft_jobs` / `scene_drafts`。节点 4.1 建 `extract_jobs` / `candidate_changes`。节点 4.2 给候选加批准 / 提交列。节点 4.3 建 `summary_jobs` / `scene_summaries` / `chapter_summaries`。节点 5.1 建 `validation_runs` / `validation_reports`。节点 5.2 建 `repair_tasks`。节点 6.1 建 `context_packs`。节点 6.2 建 `outline_revisions`。

### 运行后端

在已激活的 venv 中，于仓库根目录：

```bash
uvicorn slove_context.app:app --app-dir backend --host 127.0.0.1 --port 8000
```

### 探测 /healthz

进程内测试（不需要 Docker、不调用任何外部模型）：

```bash
make test
```

若后端已在本机监听：

```bash
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/version
```

`/healthz` 应返回 `{"status":"ok"}`。`/version` 返回带版本字符串的 JSON。响应带 `X-Request-ID`。若请求已带该头，则原样回传。

节点 1.1 的骨架步骤（克隆、复制 `.env.example`、venv、`make test`）仍然适用；1.2 在其上增加了 Postgres 与上述两个路由；1.3 增加 request_id、JSON 日志与审计框架；2.1 增加 Story Project / Spec API；2.2 增加最小 Canon API；2.3 增加 Canon Snapshot 冻结与回放；3.1 增加 Scene Card 与场景依赖；3.2 增加 LLM Gateway（仅 Fake Provider）；3.3 增加 Scene Plan 作业；3.4 增加 Scene Draft 作业（不可变修订，仅 Fake Provider）；4.1 增加 Candidate Change 抽取；4.2 增加人类批准 / 提交；4.3 增加 Scene / Chapter 摘要；5.1 增加 Validation Run；5.2 增加 Repair Task；6.1 增加 Context Pack 组装器；6.2 增加 Outline Revision。批准 Spec、批准 / 废弃 / supersede Canon 事实、冻结 Snapshot、或批准 Scene Card 必须带显式人类演员（如 `X-Actor-Type: human_editor`）。系统 / 生成 Agent / 审校 Agent 不能批准或冻结 Snapshot，也不能确认大纲可用。创建第二个项目会被拒绝。已批准 Spec 不能就地 PATCH，必须 `POST .../drafts` 出新修订版本。Active Canon 事实不能就地改写，必须 `POST .../supersede`。已冻结 Snapshot 只读。已批准 Scene Card 不能就地 PATCH。批准 Scene Card 不写 Canon。Gateway / Scene Plan / Scene Draft / 摘要 / Validation Run / Repair Task / Context Pack 作业不写 Canon。Scene Draft 与摘要不得自动批准或发表。Validate 通过不是批准。Repair 完成与 RecheckPassed 不是批准。Context Pack 冻结不是 Canon 批准。Outline 确认可用不是 Canon 批准，不写 Canon。已确认大纲不能就地 PATCH，必须出新 Revision。没有「生成一整章」或全书级散文入口。没有章级 Context Pack。

### Scene Draft 作业幂等（节点 3.4）

- 同一 `idempotency_key` 在作业仍为 queued / running / succeeded 时返回原作业（重复提交不另开）。
- 成功后再生成：换新 key 或省略 key，创建新作业 + 新 Revision；旧 Revision 正文与哈希保持不变，状态变为 Superseded。
- 取消是终态，不删除记录。取消后同一 key 不再复用，后续触发会开新作业。
- 失败作业保留证据，不删除。之后再触发（同一 key 或新 key）开新作业 / Revision 尝试。

### Scene / Chapter 摘要（节点 4.3）

- Scene Summary 必须引用已有 Scene Draft 的 `draft_revision_id`（以及该修订的内容哈希）。草稿缺失则拒绝。
- Chapter Summary 只汇总该章已有的 Scene Summary，不是一次生成整章散文。所需场景摘要缺失则拒绝。
- 摘要不是 Canon、不是 Scene Draft、不是 Candidate Change。作业不写 Canon，无自动批准。
- 修订不可变：同一 `idempotency_key` 在 queued / running / succeeded 时返回原作业；成功后再生成须新 key（或省略）并出新 Revision；取消是终态且不删除；失败作业可再开新作业 / Revision。
- 没有 `/chapters/generate` 或其它整章散文生成入口。

### Validation Run（节点 5.1）

- 输入必须是 Extracted 且已绑 Evidence 的候选、当前 Canon（或指定 Snapshot）、以及已写定 / 生效的 Story Spec。
- 规则确定：对照 Active 事实冲突与 Story Spec forbid-list。不调用真实模型。
- Passed 只把候选送到 AwaitingVerdict；不是批准，不写 Canon。
- RuleFailed / ExecFailed 不得进入批准。失败 / 取消保留记录。
- 对照 `contracts/validation-report.schema.json`。无自动批准。

### Repair Task（节点 5.2）

- 只能从 RuleFailed Validation Report / Violation 开立。Passed、仅 ExecFailed、无 Violation 会被拒绝。
- 状态：Opened / InProgress / Completed / Rechecking / RecheckPassed / Failed / Cancelled / Rework。
- `action` 仅允许 ReviseScenePlan / Regenerate / Reextract / HumanReject。
- Completed 之后必须再跑 5.1 Validation Run（Completed → Rechecking）。不得跳过再校验。
- RecheckPassed 只表示新候选可交裁决；不是批准，不写 Canon。再校验失败不得进入批准。
- HumanReject 拒绝 FailedValidation 候选且不写 Canon。无新抽取时再校验为 N/A，仍不得批准。
- 失败 / 取消保留记录。无整章散文生成入口。无自动批准。

### Context Pack 组装（节点 6.1）

- 输入必须是一场场景、已批准 Scene Card、已写定 / 生效 Story Spec、以及冻结的 Canon Snapshot。卡未批准、规格缺失、快照缺失或未冻结则拒绝。
- 输出对照 `contracts/context-pack.schema.json`。`purpose` 仅 Generate / Validate。
- `canon_excerpts` 是指定 Snapshot 的只读摘录，不得写回 Canon。组装器是确定性复制 / 过滤，不调用真实模型。
- 冻结后不可变。再组装出新 Revision / 新 id，不得覆盖旧行。冻结不是 Canon 批准。
- 生成单位为单个场景。没有章级或全书级 Context Pack 入口。
- 失败 / 取消保留记录。不批准、不提交、不抽取。无自动批准。
- 3.4 Scene Draft 仍接受静态夹具 `context_pack_id`，也接受组装器产出的已冻结包。

### Outline Revision（节点 6.2）

- 状态：Drafting → Proposed → Confirmed；另有 Revising / Failed / Cancelled / Rework / Superseded。
- 仅人工主编可确认可用（`X-Actor-Type: human_editor`）。系统 / 生成 Agent / 审校 Agent 不能确认。
- 确认可用不是 Approval，不写 Canon。大纲不是生成单位。
- 已确认版本不能就地 PATCH。结构改动必须 `POST .../revise` 出新 Revision / 新 id。旧 Confirmed 在新版确认后变为 Superseded。
- 层次为 Story → Arc/Volume → Chapter → Scene。场景节点引用已有 3.1 Scene，不重建 Scene Card，不启动生成作业。
- 节点至少含 goal、conflict、turning_point、start_state、end_state、constraints。
- 失败 / 取消保留记录。没有 `/chapters/generate` 或全书级生成入口。

### 日志长什么样

标准输出每行一条 JSON。请求完成记录至少含 `timestamp`、`level`、`request_id`、`operation`、`duration_ms`：

```json
{"timestamp":"2026-08-18T03:40:00.001234+00:00","level":"INFO","message":"request complete","request_id":"client-supplied-or-generated","operation":"GET /healthz","duration_ms":1.25}
```

不写请求体、故事正文、模型 Prompt 或 API 密钥。脱敏策略见 `docs/audit.md`。

### 迁移

迁移文件在 `backend/alembic/versions/`。节点 1.3：`001_create_audit_events.py`。节点 2.1：`002_create_story_project_and_spec.py`（`story_projects`、`story_specs`、`story_spec_versions`）。节点 2.2：`003_create_canon_tables.py`（`entities`、`evidence_records`、`canon_facts`、`canon_fact_versions`、`canon_snapshots`）。节点 2.3：`004_canon_snapshot_columns.py`（给 `canon_snapshots` 加 `fact_ids`、`frozen_at`、`as_of_scene_seq`、`as_of_story_time`、`status`）。节点 3.1：`005_create_scene_tables.py`（`arcs`、`chapters`、`scenes`、`scene_dependencies`）。节点 3.2 不新建表。节点 3.3：`006_create_scene_plan_tables.py`（`scene_plan_jobs`、`scene_plans`）。节点 3.4：`007_create_scene_draft_tables.py`（`scene_draft_jobs`、`scene_drafts`）。节点 4.1：`008_create_extract_tables.py`。节点 4.2：`009_candidate_approval.py`。节点 4.3：`010_create_summary_tables.py`（`summary_jobs`、`scene_summaries`、`chapter_summaries`）。节点 5.1：`011_create_validation_tables.py`（`validation_runs`、`validation_reports`）。节点 5.2：`012_create_repair_tasks.py`（`repair_tasks`）。节点 6.1：`013_create_context_packs.py`（`context_packs`）。节点 6.2：`014_create_outline_revisions.py`（`outline_revisions`）。无向量列。无整章散文生成表。

本地对 Postgres 建表（单元测试不需要这一步）：

```bash
docker compose up -d postgres
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 用内存 `InMemoryAuditSink` 测审计写入与脱敏，不连 Postgres，不调用外部模型。

### 叙事一致性评测（节点 9.1）

- 数据在 `evals/cases/`、`evals/fixtures/`、`evals/expected/`。每案含 Story Spec、Canon Snapshot、Scene Card、Context Pack、Draft、期望候选与违规，以及难度 / 规则类别 / 严重度 / 人工裁决依据。
- 确定性 runner：`python -m slove_context.evals --out /tmp/narrative-eval.json`。复用 5.x 硬规则；仅伏笔遗失使用 eval-only 检查。不写 Canon，不批准，不调真实模型。
- 不是 9.3 发布门。无评测 HTTP 路由。9.2 实验运行只读引用本案例集。

### 实验运行与基线对比（节点 9.2）

- 钉死 9.1 案例后可替换 model / prompt_version / retrieval_strategy / temperature / max_tokens。
- 每条 Run 记录完整配置、输入版本、输出引用、六项指标、token 成本与延迟。可与基线 Run 对比并导出 CSV / JSON。
- 历史 Run 只读。改 prompt_version 出新 Run，未冻结 Prompt 不得覆盖旧记录。
- 仅 Fake Provider。不写 Canon，不批准。不是 9.3 发布门。

### 工作流前端 Demo（节点 UI.1）

本地可点击的中文工作流 Demo。只读已落地 2.1–9.3 API，仅 Fake Provider。不是 10.x，不是真实模型集成。每页有横幅「Demo / Fake Provider / 非真实模型」。

先播种并同时启动后端 + 前端：

```bash
make demo
```

浏览器打开 **http://127.0.0.1:5173**。后端在 `http://127.0.0.1:8000`。

只播种、不启动服务：

```bash
python3 -m slove_context.demo --seed-only
```

播种是 CLI（`python -m slove_context.demo`），**不是**生产 seed-status HTTP。开发态 CORS 仅放行 Vite origin（`http://localhost:5173` / `http://127.0.0.1:5173`）；`SLOVE_ENV=production` 时不开放 `*`。审校「批准」走既有 7.3 / 4.2，不自动提交 Canon；「提交 Canon」是单独按钮。

前端测试（无浏览器窗口、无真实模型）：

```bash
make frontend-test
```

## 测试

```bash
make test
# 或
python3 -m pytest tests contracts
```

`tests/test_healthz.py` 用 FastAPI `TestClient` 在进程内检查 `/healthz`（以及 `/version`）。`tests/test_request_id.py` 检查 `X-Request-ID` 与 JSON 请求日志字段。`tests/test_audit.py` 检查审计写入与脱敏。`tests/test_story_project_spec.py` 检查 Story Project / Spec（schema 422、未批准不得当作已批准、已批准禁止 PATCH）。`tests/test_canon.py` 检查 Canon 实体 / 证据 / 事实（NotInCanon 创建、仅人工主编批准或废弃、故事时间查询、supersede 只追加）。`tests/test_canon_snapshot.py` 检查 Snapshot 创建 / 冻结 / 查询 / diff / 回放（后期新事实不得泄漏、仅人类冻结、稳定排序）。`tests/test_scene_card.py` 检查 Scene Card / 顺序 / 依赖（schema 422、依赖阻断可生成、环依赖、故事顺序冲突、仅人类批准）。`tests/test_llm_gateway.py` 检查 LLM Gateway（Fake 夹具、超时、重试耗尽、结构化解析失败、日志脱敏、禁止重试写路径）。`tests/test_scene_plan.py` 检查 Scene Plan 作业。`tests/test_scene_draft.py` 检查 Scene Draft 作业（修订不可变、幂等、失败、取消、审计脱敏）。`tests/test_candidate_change.py` 与 `tests/test_candidate_approval.py` 检查抽取与人类批准 / 提交。`tests/test_summaries.py` 检查 Scene / Chapter 摘要（须基于草稿、章级汇总、修订不可变、不写 Canon、无整章生成入口）。`tests/test_validation_run.py` 检查 Validation Run（Passed → AwaitingVerdict、RuleFailed 阻断、ExecFailed、非 Extracted 拒绝、不写 Canon）。`tests/test_repair_task.py` 检查 Repair Task（仅 RuleFailed 可开立、完成后强制再校验、RecheckPassed 不批准、再校验失败阻断批准、取消不删除）。`tests/test_context_pack.py` 检查 Context Pack 组装（Generate / Validate、缺卡 / 规格 / 快照拒绝、不写 Canon、无章级包、冻结后不可变）。`tests/test_outline_revision.py` 检查 Outline Revision（拟定 / 提交确认 / 确认可用、确认不是 Canon 批准、已确认禁止就地改、无章级生成、失败 / 取消不删除）。`tests/test_narrative_evals.py` 检查节点 9.1 评测集（九类可加载、确定性规则命中期望、runner JSON / 指标、不写 Canon / 不批准）。`tests/test_experiments.py` 检查节点 9.2 实验运行（创建、替换配置、基线六项指标对比、CSV/JSON 导出、历史不可变、不写 Canon / 不批准）。不启动 Docker，不调用真实模型，无网络。同一命令会收集 `contracts/` 下已批准 Schema 的校验测试。

结束实现前按 `AGENTS.md`：格式化、类型检查、测试。

```bash
make format
make lint
make typecheck
make test
# 或
make check
```

## 环境变量

见 `.env.example`。名称与占位值（如 `changeme`）仅供本地示例，不是真实密钥。`/healthz` 与 `/version` 不读取这些变量。Alembic 本地迁移可读 `DATABASE_URL`。禁止把真实 API 密钥、正文敏感内容或模型输出写入仓库。

## 实现约定

见根目录 `AGENTS.md`。每次只处理一个任务 ID；先读 docs 与 contracts。
