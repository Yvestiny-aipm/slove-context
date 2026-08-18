# AGENTS.md

本文件给在本仓库工作的实现 bot / 验收 bot 的硬规则。  
一次只实现一个已冻结节点。当前节点是 2.1：Story Project 与 Story Spec 持久化 API。不要启动节点 2.2（不要做 Canon 实体 / 事实表）。

开始任何任务前：先读 `docs/mvp-scope.md`、`docs/domain-glossary.md`、`docs/state-machines.md`、`docs/architecture.md` 与 `contracts/`。  
不要把未实现行为写成已完成。不要发明已落地的 Canon、鉴权、队列或模型调用。

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
