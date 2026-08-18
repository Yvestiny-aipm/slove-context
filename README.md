# slove-context
slove context

本地单机、一个故事项目、一名用户（创作者兼主编）、仅中文。候选变更须经人类主编批准或拒绝后才能提交 Canon。自动批准与多项目不是 MVP 正常行为。

节点 1.1 建立了本地单体仓库骨架。节点 1.2 在此基础上提供可运行的本地 Postgres 与 FastAPI `/healthz` / `/version`。节点 1.3 增加请求 `request_id`、JSON 结构化日志、以及 `audit_events` 迁移与通用审计写入接口。节点 2.1 增加唯一 Story Project 与 Story Spec 草稿 / 提交 / 人工批准 / 修订版本。节点 2.2 增加最小 Canon 实体 / 证据 / 事实 API（只追加，supersede 更正）。本仓库没有用户鉴权、队列或模型调用。Spec 批准不是 Canon 批准。`canon_snapshots` 只建表，没有冻结作业或回放接口。

**包管理：只用 venv**（`python3 -m venv` + `pip`）。不要加入 Poetry 或 uv。

## 目录

| 路径 | 说明 |
| --- | --- |
| `AGENTS.md` | 实现约定（八条规则）与常用命令示例 |
| `docs/` | 已冻结范围 / 术语 / 状态机，骨架边界 `architecture.md`，以及 `audit.md` |
| `contracts/` | 已批准 JSON Schema（节点 0.4） |
| `backend/` | FastAPI 应用（`/healthz`、`/version`、request_id、JSON 日志、审计写入、Story Project / Spec、最小 Canon API） |
| `backend/alembic/` | 可审阅的 `audit_events`、Story Project / Spec 与 Canon 表迁移（单元测试不连库） |
| `tests/` | `/healthz`、request_id、审计写入、Story Project / Spec、Canon 的进程内测试；`make test` 也会跑 contracts 测试 |
| `scripts/` | 脚本目录占位 |
| `data/` | 本地数据占位（不提交密钥或模型输出） |
| `docker-compose.yml` | 可启动的 Postgres（healthcheck + 持久卷） |
| `.env.example` | 环境变量名与安全注释（含 Postgres 占位） |

## 本地开始（节点 1.2 + 1.3 + 2.1 + 2.2）

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

等到 `postgres` 为 healthy。数据落在命名卷 `postgres_data`。`audit_events`、Story Project / Spec 与 Canon 表用 Alembic 建（见下方「迁移」）；单元测试不跑迁移、不连库。`canon_snapshots` 只建表，没有冻结 / 回放实现。

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

节点 1.1 的骨架步骤（克隆、复制 `.env.example`、venv、`make test`）仍然适用；1.2 在其上增加了 Postgres 与上述两个路由；1.3 增加 request_id、JSON 日志与审计框架；2.1 增加 Story Project / Spec API；2.2 增加最小 Canon API。批准 Spec 或批准 / 废弃 / supersede Canon 事实必须带显式人类演员（如 `X-Actor-Type: human_editor`）。系统 / 生成 Agent / 审校 Agent 不能批准。创建第二个项目会被拒绝。已批准 Spec 不能就地 PATCH，必须 `POST .../drafts` 出新修订版本。Active Canon 事实不能就地改写，必须 `POST .../supersede`。

### 日志长什么样

标准输出每行一条 JSON。请求完成记录至少含 `timestamp`、`level`、`request_id`、`operation`、`duration_ms`：

```json
{"timestamp":"2026-08-18T03:40:00.001234+00:00","level":"INFO","message":"request complete","request_id":"client-supplied-or-generated","operation":"GET /healthz","duration_ms":1.25}
```

不写请求体、故事正文、模型 Prompt 或 API 密钥。脱敏策略见 `docs/audit.md`。

### 迁移

迁移文件在 `backend/alembic/versions/`。节点 1.3：`001_create_audit_events.py`。节点 2.1：`002_create_story_project_and_spec.py`（`story_projects`、`story_specs`、`story_spec_versions`）。节点 2.2：`003_create_canon_tables.py`（`entities`、`evidence_records`、`canon_facts`、`canon_fact_versions`、`canon_snapshots`）。无向量列，无回放作业。

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

`tests/test_healthz.py` 用 FastAPI `TestClient` 在进程内检查 `/healthz`（以及 `/version`）。`tests/test_request_id.py` 检查 `X-Request-ID` 与 JSON 请求日志字段。`tests/test_audit.py` 检查审计写入与脱敏。`tests/test_story_project_spec.py` 检查 Story Project / Spec（schema 422、未批准不得当作已批准、已批准禁止 PATCH）。`tests/test_canon.py` 检查 Canon 实体 / 证据 / 事实（NotInCanon 创建、仅人工主编批准或废弃、故事时间查询、supersede 只追加）。不启动 Docker，不调用模型。同一命令会收集 `contracts/` 下已批准 Schema 的校验测试。

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
