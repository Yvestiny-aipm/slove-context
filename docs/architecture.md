# 架构（节点 1.1 骨架 + 节点 1.2 本地环境 + 节点 1.3 审计日志 + 节点 2.1 Story Project / Spec + 节点 2.2 最小 Canon）

本文冻结本地单体仓库的目录边界。节点 1.2 补可运行的 Postgres 与 FastAPI 健康检查。节点 1.3 只加请求 `request_id`、JSON 结构化日志、以及 `audit_events` 迁移与通用写入接口。节点 2.1 增加 Story Project / Story Spec / Revision 持久化与 API。节点 2.2 增加通用实体、证据、Canon 事实与不可变版本，以及 `canon_snapshots` 表（只建表）。  
不写实现细节，不把未实现行为写成已完成。术语与范围以节点 0.1–0.4 为准，本文不改写它们。

## 1. 形态

- 一个本地单体仓库（local monolith），在一台电脑上由一名用户使用。
- 一名用户：创作者本人，同时担任主编。
- 一个故事项目；仅中文；一个写作模型供应商；生成单位为场景。
- 候选变更必须经人类主编批准或拒绝后，才能提交 Canon。
- **自动批准不是 MVP 正常行为。**
- **多项目不是 MVP 正常行为。**

节点 1.1 提供目录与约定。节点 1.2 增加可启动的 Postgres 与仅含 `/healthz`、`/version` 的 FastAPI。节点 1.3 在其上增加请求关联、JSON 日志与审计写入框架。节点 2.1 增加唯一 Story Project 与 Story Spec 草稿 / 提交 / 人工批准 / 修订版本。节点 2.2 增加最小 Canon 读写。没有队列、模型客户端或鉴权。

## 2. 目录边界

| 路径 | 本骨架中的角色 | 本节点不表示已经做成 |
| --- | --- | --- |
| `AGENTS.md` | 实现约定（八条规则） | 不表示业务已实现 |
| `docs/` | 已冻结范围 / 术语 / 状态机，以及本文与 `audit.md` | 不表示状态机已编码 |
| `docs/audit.md` | 审计表、JSON 日志与脱敏策略 | 不表示已有快照冻结 / 回放 |
| `contracts/` | 已批准 JSON Schema（节点 0.4） | 不表示已有读写这些对象的服务 |
| `backend/` | FastAPI `/healthz`、`/version`、request_id / JSON 日志 / 审计写入，Story Project / Spec API，以及最小 Canon API | 无鉴权 / 队列 / 模型客户端；无快照冻结 / 回放；单元测试用内存仓库，不连库 |
| `backend/alembic/` | `audit_events`、Story Project / Spec 与 Canon 表的可审阅迁移 | 单元测试不跑迁移；`canon_snapshots` 只建表 |
| `tests/` | `/healthz`、request_id、审计写入、Story Project / Spec、Canon 的进程内测试；可收集 `contracts/` 测试 | 不需要 live Postgres；无模型调用 |
| `scripts/` | 脚本目录占位 | 无业务命令 |
| `data/` | 本地数据目录占位 | 不存放密钥、正文敏感内容或模型输出（见 `.gitignore`） |
| `docker-compose.yml` | 可启动的 Postgres（healthcheck + 持久卷） | 无 backend 容器（可选） |
| `.env.example` | 变量名与安全注释 | 不读取、不连接、不含真实密钥 |
| `Makefile` | `install` / `format` / `lint` / `typecheck` / `test` | 不启动服务 |

## 3. 本仓库包含（节点 1.1 + 1.2 + 1.3 + 2.1 + 2.2）

- 仓库根约定：`AGENTS.md`、`.gitignore`、`.env.example`、`Makefile`。
- 目录占位：`backend/`、`tests/`、`scripts/`、`data/`。
- 边界说明：本文；脱敏与审计说明：`docs/audit.md`。
- 编排：`docker-compose.yml` 启动 Postgres（healthcheck + 命名卷）。
- FastAPI：`GET /healthz` 与 `GET /version`（保留）；请求中间件补 `request_id` 与 JSON 请求完成日志。
- 通用 `AuditWriter` + `AuditSink`（测试用内存 sink）。写操作走该路径。
- Alembic：`audit_events`（1.3）、`story_projects` / `story_specs` / `story_spec_versions`（2.1），以及 `entities` / `evidence_records` / `canon_facts` / `canon_fact_versions` / `canon_snapshots`（2.2）手写迁移。
- Story Project / Story Spec API：创建唯一项目、创建草稿、读取、提交写定、仅人工主编批准、列 Revision、批准后以新草稿 Revision 改写。对照 `contracts/story-spec.schema.json`。
- 最小 Canon API：通用实体、证据、Canon 事实创建（NotInCanon）、仅人工主编批准 / 废弃 / supersede、按项目 / 实体 / 谓语 / 故事时间查询生效的 Active 事实。事实只追加，禁止就地改 Active 正文。
- 进程内测试：`/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon（以及已有的 contracts 校验）。不连 Postgres，不调用模型。

## 4. 本节点明确不是

下列项不属于节点 2.2，不得当作本节点已交付：

- 快照冻结作业、回放接口或把 `canon_snapshots` 写成已可冻结 / 回放（节点 2.3）。
- 向量检索、图数据库、自动抽取、LLM / 模型调用。
- 把角色 / 场景做成小说写作产品（实体只是通用对象）。
- 用户鉴权、队列。
- 自动批准、多项目、第二语言或第二模型供应商。
- 修改已批准的 `docs/mvp-scope.md`、`docs/domain-glossary.md`、`docs/state-machines.md` 或 `contracts/` 既有文件。
- 候选变更自动变成 Canon 事实。

## 5. 与已冻结文档的关系

实现必须服从：

- `docs/mvp-scope.md`（节点 0.1）
- `docs/domain-glossary.md`（节点 0.2）
- `docs/state-machines.md`（节点 0.3）
- `contracts/`（节点 0.4）

本文只画仓库边界，不重复定义术语，不把 Schema 对象写成已经落地的服务。
