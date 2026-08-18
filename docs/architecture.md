# 架构（节点 1.1 骨架 + 节点 1.2 本地环境）

本文冻结本地单体仓库的目录边界。节点 1.2 只补可运行的 Postgres 与 FastAPI 健康检查。  
不写实现细节，不把未实现行为写成已完成。术语与范围以节点 0.1–0.4 为准，本文不改写它们。

## 1. 形态

- 一个本地单体仓库（local monolith），在一台电脑上由一名用户使用。
- 一名用户：创作者本人，同时担任主编。
- 一个故事项目；仅中文；一个写作模型供应商；生成单位为场景。
- 候选变更必须经人类主编批准或拒绝后，才能提交 Canon。
- **自动批准不是 MVP 正常行为。**
- **多项目不是 MVP 正常行为。**

节点 1.1 提供目录与约定。节点 1.2 增加可启动的 Postgres 与仅含 `/healthz`、`/version` 的 FastAPI。没有队列、模型客户端、鉴权或 Canon 读写。

## 2. 目录边界

| 路径 | 本骨架中的角色 | 本节点不表示已经做成 |
| --- | --- | --- |
| `AGENTS.md` | 实现约定（八条规则） | 不表示业务已实现 |
| `docs/` | 已冻结范围 / 术语 / 状态机，以及本文 | 不表示状态机已编码 |
| `contracts/` | 已批准 JSON Schema（节点 0.4） | 不表示已有读写这些对象的服务 |
| `backend/` | FastAPI `/healthz` 与 `/version` | 无业务逻辑；无 Canon / 鉴权 / 队列 / 模型客户端；无数据库连接代码 |
| `tests/` | `/healthz` 进程内测试与占位测试；可收集 `contracts/` 测试 | 无小说业务测试 |
| `scripts/` | 脚本目录占位 | 无业务命令 |
| `data/` | 本地数据目录占位 | 不存放密钥、正文敏感内容或模型输出（见 `.gitignore`） |
| `docker-compose.yml` | 可启动的 Postgres（healthcheck + 持久卷） | 无 backend 容器（可选）；无 Canon 表 |
| `.env.example` | 变量名与安全注释 | 不读取、不连接、不含真实密钥 |
| `Makefile` | `install` / `format` / `lint` / `typecheck` / `test` | 不启动服务 |

## 3. 本仓库包含（节点 1.1 + 1.2）

- 仓库根约定：`AGENTS.md`、`.gitignore`、`.env.example`、`Makefile`。
- 目录占位：`backend/`、`tests/`、`scripts/`、`data/`。
- 边界说明：本文。
- 编排：`docker-compose.yml` 启动 Postgres（healthcheck + 命名卷）。
- FastAPI：仅 `GET /healthz` 与 `GET /version`。
- 可运行的 `/healthz` 进程内测试（以及已有的 contracts 校验）。

## 4. 本节点明确不是

下列项不属于节点 1.2，不得当作本节点已交付：

- Canon 表、Canon 写入 / 读取逻辑、校验引擎、场景生成。
- 用户鉴权、队列、模型调用。
- 节点 1.3 的审计 / 结构化日志系统。
- 小说写作业务功能。
- 自动批准、多项目、第二语言或第二模型供应商。
- 修改已批准的 `docs/mvp-scope.md`、`docs/domain-glossary.md`、`docs/state-machines.md` 或 `contracts/` 既有文件。

## 5. 与已冻结文档的关系

实现必须服从：

- `docs/mvp-scope.md`（节点 0.1）
- `docs/domain-glossary.md`（节点 0.2）
- `docs/state-machines.md`（节点 0.3）
- `contracts/`（节点 0.4）

本文只画仓库边界，不重复定义术语，不把 Schema 对象写成已经落地的服务。
