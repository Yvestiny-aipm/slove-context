# slove-context
slove context

本地单机、一个故事项目、一名用户（创作者兼主编）、仅中文。候选变更须经人类主编批准或拒绝后才能提交 Canon。自动批准与多项目不是 MVP 正常行为。

节点 1.1 只建立本地单体仓库骨架，**没有**可运行的 FastAPI 或 Postgres。可运行的健康检查属于节点 1.2，本节点不做。

## 目录

| 路径 | 说明 |
| --- | --- |
| `AGENTS.md` | 实现约定（八条规则） |
| `docs/` | 已冻结范围 / 术语 / 状态机，以及骨架边界 `architecture.md` |
| `contracts/` | 已批准 JSON Schema（节点 0.4） |
| `backend/` | Python 包骨架，无业务逻辑 |
| `tests/` | 骨架占位测试；`make test` 也会跑 contracts 测试 |
| `scripts/` | 脚本目录占位 |
| `data/` | 本地数据占位（不提交密钥或模型输出） |
| `docker-compose.yml` | 服务占位；1.1 不启动 |
| `.env.example` | 环境变量名与安全注释 |

## 本地开始（节点 1.1）

本节点没有要启动的 API 或数据库。不要用 `docker compose up` 去等健康的 Postgres / FastAPI——那是 1.2。

1. 克隆本仓库。
2. 复制 `.env.example` 为 `.env`。不要填入真实密钥，也不要把 `.env` 提交到 Git。
3. 建议使用虚拟环境：`python3 -m venv .venv && source .venv/bin/activate`
4. 安装测试依赖：`make install`（或 `python3 -m pip install -r contracts/requirements.txt`）
5. 运行测试：`make test`

## 测试

```bash
make test
# 或
python3 -m pytest tests contracts
```

`tests/` 含骨架占位测试。同一命令会收集 `contracts/` 下已批准 Schema 的校验测试。

结束实现前按 `AGENTS.md`：格式化、类型检查、测试。本节点无应用代码，`make format` 与 `make typecheck` 为空操作；`make check` 会跑这三项。

## 环境变量

见 `.env.example`。节点 1.1 不读取这些变量。名称仅作占位。禁止把真实 API 密钥、正文敏感内容或模型输出写入仓库。

## 实现约定

见根目录 `AGENTS.md`。每次只处理一个任务 ID；先读 docs 与 contracts。
