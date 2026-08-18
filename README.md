# slove-context
slove context

本地单机、一个故事项目、一名用户（创作者兼主编）、仅中文。候选变更须经人类主编批准或拒绝后才能提交 Canon。自动批准与多项目不是 MVP 正常行为。

节点 1.1 建立了本地单体仓库骨架。节点 1.2 在此基础上提供可运行的本地 Postgres 与 FastAPI `/healthz` / `/version`。本节点没有 Canon、用户鉴权、队列或模型调用。

**包管理：只用 venv**（`python3 -m venv` + `pip`）。不要加入 Poetry 或 uv。

## 目录

| 路径 | 说明 |
| --- | --- |
| `AGENTS.md` | 实现约定（八条规则）与常用命令示例 |
| `docs/` | 已冻结范围 / 术语 / 状态机，以及骨架边界 `architecture.md` |
| `contracts/` | 已批准 JSON Schema（节点 0.4） |
| `backend/` | FastAPI 应用（仅 `/healthz` 与 `/version`） |
| `tests/` | `/healthz` 进程内测试与骨架占位测试；`make test` 也会跑 contracts 测试 |
| `scripts/` | 脚本目录占位 |
| `data/` | 本地数据占位（不提交密钥或模型输出） |
| `docker-compose.yml` | 可启动的 Postgres（healthcheck + 持久卷） |
| `.env.example` | 环境变量名与安全注释（含 Postgres 占位） |

## 本地开始（节点 1.2）

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

等到 `postgres` 为 healthy。数据落在命名卷 `postgres_data`。本节点不建 Canon 表、不跑迁移。

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

`/healthz` 应返回 `{"status":"ok"}`。`/version` 返回带版本字符串的 JSON。

节点 1.1 的骨架步骤（克隆、复制 `.env.example`、venv、`make test`）仍然适用；1.2 在其上增加了 Postgres 与上述两个路由。

## 测试

```bash
make test
# 或
python3 -m pytest tests contracts
```

`tests/test_healthz.py` 用 FastAPI `TestClient` 在进程内检查 `/healthz`（以及 `/version`），不启动 Docker，不调用模型。同一命令会收集 `contracts/` 下已批准 Schema 的校验测试。

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

见 `.env.example`。名称与占位值（如 `changeme`）仅供本地示例，不是真实密钥。节点 1.2 的 `/healthz` 与 `/version` 不读取这些变量。禁止把真实 API 密钥、正文敏感内容或模型输出写入仓库。

## 实现约定

见根目录 `AGENTS.md`。每次只处理一个任务 ID；先读 docs 与 contracts。
