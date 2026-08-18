# slove-context
slove context

本地单机、一个故事项目、一名用户（创作者兼主编）、仅中文。候选变更须经人类主编批准或拒绝后才能提交 Canon。自动批准与多项目不是 MVP 正常行为。

节点 1.1 建立了本地单体仓库骨架。节点 1.2 在此基础上提供可运行的本地 Postgres 与 FastAPI `/healthz` / `/version`。节点 1.3 增加请求 `request_id`、JSON 结构化日志、以及 `audit_events` 迁移与通用审计写入接口。节点 2.1 增加唯一 Story Project 与 Story Spec 草稿 / 提交 / 人工批准 / 修订版本。节点 2.2 增加最小 Canon 实体 / 证据 / 事实 API（只追加，supersede 更正）。节点 2.3 增加 Canon Snapshot 创建、冻结、按 snapshot_id 查询、diff 与回放。节点 3.1 增加 Scene Card、故事内顺序与场景依赖（卷 / 章仅为结构容器）。节点 3.2 增加可替换 LLM Gateway 与仅 Fake Provider（夹具，无外部模型 HTTP）。节点 3.3 增加 Scene Plan 生成作业。节点 3.4 增加 Scene Draft 生成作业（不可变修订版本；仅 Fake Provider）。本仓库没有用户鉴权、队列或真实模型调用。Spec 批准与 Scene Card 批准都不是 Canon 批准。快照不代替当前 Canon。没有 Context Pack 组装器或自动事实抽取。

**包管理：只用 venv**（`python3 -m venv` + `pip`）。不要加入 Poetry 或 uv。

## 目录

| 路径 | 说明 |
| --- | --- |
| `AGENTS.md` | 实现约定（八条规则）与常用命令示例 |
| `docs/` | 已冻结范围 / 术语 / 状态机，骨架边界 `architecture.md`，以及 `audit.md` |
| `contracts/` | 已批准 JSON Schema（节点 0.4） |
| `backend/` | FastAPI 应用（`/healthz`、`/version`、request_id、JSON 日志、审计写入、Story Project / Spec、最小 Canon API、Canon Snapshot、Scene Card、LLM Gateway、Scene Plan / Scene Draft 作业） |
| `backend/alembic/` | 可审阅的 `audit_events`、Story Project / Spec、Canon 表、snapshot 列、Scene / Scene Plan / Scene Draft 表迁移（单元测试不连库） |
| `tests/` | `/healthz`、request_id、审计写入、Story Project / Spec、Canon、Snapshot、Scene Card、LLM Gateway、Scene Plan / Scene Draft 的进程内测试；`make test` 也会跑 contracts 测试 |
| `scripts/` | 脚本目录占位 |
| `data/` | 本地数据占位（不提交密钥或模型输出） |
| `docker-compose.yml` | 可启动的 Postgres（healthcheck + 持久卷） |
| `.env.example` | 环境变量名与安全注释（含 Postgres 占位） |

## 本地开始（节点 1.2 + 1.3 + 2.1 + 2.2 + 2.3 + 3.1 + 3.2 + 3.3 + 3.4）

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

等到 `postgres` 为 healthy。数据落在命名卷 `postgres_data`。`audit_events`、Story Project / Spec、Canon 表、snapshot 列、Scene / Scene Plan / Scene Draft 表用 Alembic 建（见下方「迁移」）；单元测试不跑迁移、不连库。`canon_snapshots` 在 2.2 建表，2.3 增量加冻结 / 回放列。节点 3.1 建 `arcs` / `chapters` / `scenes` / `scene_dependencies`。节点 3.3 建 `scene_plan_jobs` / `scene_plans`。节点 3.4 建 `scene_draft_jobs` / `scene_drafts`。

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

节点 1.1 的骨架步骤（克隆、复制 `.env.example`、venv、`make test`）仍然适用；1.2 在其上增加了 Postgres 与上述两个路由；1.3 增加 request_id、JSON 日志与审计框架；2.1 增加 Story Project / Spec API；2.2 增加最小 Canon API；2.3 增加 Canon Snapshot 冻结与回放；3.1 增加 Scene Card 与场景依赖；3.2 增加 LLM Gateway（仅 Fake Provider）；3.3 增加 Scene Plan 作业；3.4 增加 Scene Draft 作业（不可变修订，仅 Fake Provider）。批准 Spec、批准 / 废弃 / supersede Canon 事实、冻结 Snapshot、或批准 Scene Card 必须带显式人类演员（如 `X-Actor-Type: human_editor`）。系统 / 生成 Agent / 审校 Agent 不能批准或冻结。创建第二个项目会被拒绝。已批准 Spec 不能就地 PATCH，必须 `POST .../drafts` 出新修订版本。Active Canon 事实不能就地改写，必须 `POST .../supersede`。已冻结 Snapshot 只读。已批准 Scene Card 不能就地 PATCH。批准 Scene Card 不写 Canon。Gateway / Scene Plan / Scene Draft 作业不写 Canon。Scene Draft 不得自动批准或发表。

### Scene Draft 作业幂等（节点 3.4）

- 同一 `idempotency_key` 在作业仍为 queued / running / succeeded 时返回原作业（重复提交不另开）。
- 成功后再生成：换新 key 或省略 key，创建新作业 + 新 Revision；旧 Revision 正文与哈希保持不变，状态变为 Superseded。
- 取消是终态，不删除记录。取消后同一 key 不再复用，后续触发会开新作业。
- 失败作业保留证据，不删除。之后再触发（同一 key 或新 key）开新作业 / Revision 尝试。

### 日志长什么样

标准输出每行一条 JSON。请求完成记录至少含 `timestamp`、`level`、`request_id`、`operation`、`duration_ms`：

```json
{"timestamp":"2026-08-18T03:40:00.001234+00:00","level":"INFO","message":"request complete","request_id":"client-supplied-or-generated","operation":"GET /healthz","duration_ms":1.25}
```

不写请求体、故事正文、模型 Prompt 或 API 密钥。脱敏策略见 `docs/audit.md`。

### 迁移

迁移文件在 `backend/alembic/versions/`。节点 1.3：`001_create_audit_events.py`。节点 2.1：`002_create_story_project_and_spec.py`（`story_projects`、`story_specs`、`story_spec_versions`）。节点 2.2：`003_create_canon_tables.py`（`entities`、`evidence_records`、`canon_facts`、`canon_fact_versions`、`canon_snapshots`）。节点 2.3：`004_canon_snapshot_columns.py`（给 `canon_snapshots` 加 `fact_ids`、`frozen_at`、`as_of_scene_seq`、`as_of_story_time`、`status`）。节点 3.1：`005_create_scene_tables.py`（`arcs`、`chapters`、`scenes`、`scene_dependencies`）。节点 3.2 不新建表。节点 3.3：`006_create_scene_plan_tables.py`（`scene_plan_jobs`、`scene_plans`）。节点 3.4：`007_create_scene_draft_tables.py`（`scene_draft_jobs`、`scene_drafts`）。无向量列，无 Candidate Change / Context Pack 组装表。

本地对 Postgres 建表（单元测试不需要这一步）：

```bash
docker compose up -d postgres
make migrate
# 或
cd backend && alembic upgrade head
```

`make test` 用内存 `InMemoryAuditSink` 测审计写入与脱敏，不连 Postgres，不调用外部模型。

## 测试

```bash
make test
# 或
python3 -m pytest tests contracts
```

`tests/test_healthz.py` 用 FastAPI `TestClient` 在进程内检查 `/healthz`（以及 `/version`）。`tests/test_request_id.py` 检查 `X-Request-ID` 与 JSON 请求日志字段。`tests/test_audit.py` 检查审计写入与脱敏。`tests/test_story_project_spec.py` 检查 Story Project / Spec（schema 422、未批准不得当作已批准、已批准禁止 PATCH）。`tests/test_canon.py` 检查 Canon 实体 / 证据 / 事实（NotInCanon 创建、仅人工主编批准或废弃、故事时间查询、supersede 只追加）。`tests/test_canon_snapshot.py` 检查 Snapshot 创建 / 冻结 / 查询 / diff / 回放（后期新事实不得泄漏、仅人类冻结、稳定排序）。`tests/test_scene_card.py` 检查 Scene Card / 顺序 / 依赖（schema 422、依赖阻断可生成、环依赖、故事顺序冲突、仅人类批准）。`tests/test_llm_gateway.py` 检查 LLM Gateway（Fake 夹具、超时、重试耗尽、结构化解析失败、日志脱敏、禁止重试写路径）。`tests/test_scene_plan.py` 检查 Scene Plan 作业。`tests/test_scene_draft.py` 检查 Scene Draft 作业（修订不可变、幂等、失败、取消、审计脱敏）。不启动 Docker，不调用真实模型，无网络。同一命令会收集 `contracts/` 下已批准 Schema 的校验测试。

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
