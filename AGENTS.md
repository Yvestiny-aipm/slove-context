# AGENTS.md

本文件给在本仓库工作的实现 bot / 验收 bot 的硬规则。  
一次只实现一个已冻结节点。当前节点是 3.1：Scene Card、场景顺序与依赖。不要启动节点 3.2（不要做模型网关）。不要生成 Scene Plan 或 Scene Draft。不要实现 Context Pack 或生成器。不要加入向量检索或 LLM。

开始任何任务前：先读 `docs/mvp-scope.md`、`docs/domain-glossary.md`、`docs/state-machines.md`、`docs/architecture.md` 与 `contracts/`。  
不要把未实现行为写成已完成。不要发明已落地的鉴权、队列、模型调用、Context Pack、生成器或节点 3.2 模型网关。

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
