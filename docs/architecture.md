# 架构（节点 1.1 骨架 + 节点 1.2 本地环境 + 节点 1.3 审计日志 + 节点 2.1 Story Project / Spec + 节点 2.2 最小 Canon + 节点 2.3 Canon Snapshot + 节点 3.1 Scene Card + 节点 3.2 LLM Gateway + 节点 3.3 Scene Plan 作业 + 节点 3.4 Scene Draft 作业 + 节点 4.1 Candidate Change 抽取作业 + 节点 4.2 人类批准与提交 Canon + 节点 4.3 Scene / Chapter 摘要 + 节点 5.1 Validation Run + 节点 5.2 Repair Task + 节点 6.1 Context Pack 组装器 + 节点 6.2 Outline Revision + 节点 7.1 Style Guide / Style Sample + 节点 7.2 Style Validation + 节点 7.3 人类审校队列 + 节点 8.1 本地作业队列与 Worker + 节点 8.2 Agent 注册表与权限 + 节点 8.3 单场景 DAG + 节点 8.4 批量调度 + 节点 9.1 叙事一致性评测 + 节点 9.2 实验运行与基线对比 + 节点 9.3 发布门与全书导出）

本文冻结本地单体仓库的目录边界。节点 1.2 补可运行的 Postgres 与 FastAPI 健康检查。节点 1.3 只加请求 `request_id`、JSON 结构化日志、以及 `audit_events` 迁移与通用写入接口。节点 2.1 增加 Story Project / Story Spec / Revision 持久化与 API。节点 2.2 增加通用实体、证据、Canon 事实与不可变版本，以及 `canon_snapshots` 表（只建表）。节点 2.3 在该表上增加冻结 / 查询 / diff / 回放。节点 3.1 增加 Scene Card、故事内顺序与场景依赖（卷 / 章仅为结构容器）。节点 3.2 增加可替换 LLM Gateway 与仅 Fake Provider（夹具，无外部模型 HTTP）。节点 3.3 增加 Scene Plan 生成作业（仅 Fake Provider；对照 `contracts/scene-plan.schema.json`；至多一次 format repair）。节点 3.4 增加 Scene Draft 生成作业（仅 Fake Provider；不可变修订版本；预冻结 Context Pack 引用）。节点 4.1 增加 Candidate Change 抽取作业（仅 Fake Provider；对照 `contracts/candidate-change.schema.json`；每条绑定 Evidence；至多一次 format repair）。节点 4.2 增加人类主编对候选变更的批准 / 拒绝 / 提交（对照 `contracts/approval-decision.schema.json`；批准不写 Canon；提交才创建或 supersede Canon Fact）。节点 4.3 增加 Scene / Chapter 摘要作业（仅 Fake Provider；场景摘要基于已有草稿修订；章摘要由场景摘要汇总，不是整章散文生成）。节点 5.1 增加 Validation Run（确定性规则；对照 Canon / Snapshot 与已写定 Story Spec；对照 `contracts/validation-report.schema.json`；通过不是批准，不写 Canon）。节点 5.2 增加 Repair Task（仅从 RuleFailed / Violation 开立；完成后必须再跑 Validation Run；RecheckPassed 不是批准，不写 Canon）。节点 6.1 增加 Context Pack 组装器（确定性；对照 `contracts/context-pack.schema.json`；只读 Snapshot 摘录；冻结后不可变；不是 Canon，不是批准）。节点 6.2 增加 Outline Revision（拟定 → 提交确认 → 仅人工主编确认可用；确认不是批准，不写 Canon；已确认版本不可就地改，须出新 Revision）。节点 7.1 增加版本化 Style Guide / Style Sample（仅人工主编批准 / 授权；批准不是 Canon 批准，不写 Canon；冻结后不可就地改，须出新 Revision）。节点 7.2 增加 Style Validation v1（确定性检查 + Fake Provider 对照已批准 Style Guide；发现默认 warning / info，不阻断 Canon 提交；不是 5.x Validation Run，不写 Canon）。节点 7.3 增加人类审校队列（入队已有 Scene Plan / Scene Draft / Candidate Change / Validation Report / Repair Task / Style Report；仅人工主编裁决；候选 approve 复用 4.2 裁决不 submit；风格报告批准不是 Canon 批准）。节点 8.1 增加本地作业队列与进程内 Worker（按 job_type 分发到既有 3.3–6.1 服务；同场写作业互斥；幂等 / 超时 / 退避 / dead-letter / 人工 rerun；Worker 不批准、不写 Canon）。节点 8.2 增加 Agent 注册表与权限边界（七类 Agent；服务层再检查；未授权 403；Run 可回放；任何 Agent 不得绕过 Approval 写 Canon；Human Approver 是唯一 Canon 批准角色）。节点 8.3 增加单场景 DAG 编排器（固定节点与依赖；经 8.1 Worker / 8.2 权限分发；human_review / canon_commit 等待人类主编；canon_commit 仅在批准后走既有 4.2 submit；blocker 阻断后续自动 submit；按节点 rerun 默认复用冻结上游）。节点 8.4 增加批量项目 / 章调度（经既有 DAG + Worker + PermissionGuard；同项目仅依赖已批准的场景可入队；预算或连续失败则暂停并告警人类；dry-run 不调模型、不入队写作业、不写 Canon）。节点 9.1 增加叙事一致性评测数据格式、九类样本与确定性 runner（复用 5.x 硬规则；不写 Canon；不是发布门）。节点 9.2 增加 Experiment Run：在已钉死的 9.1 案例上替换 model / prompt_version / retrieval_strategy / temperature / max_tokens，与基线 Run 对比六项指标，并导出 CSV / JSON（仅 Fake Provider；不写 Canon；不是 9.3 发布门）。节点 9.3 增加发布门与全书导出：八项只读预发布检查；全部通过才出不可变 Release Manifest 与正式导出（Markdown / JSON / 审校包）；任一失败返回机器可读失败列表并禁止正式导出。不写 Canon，不批准，不生成新散文。  
不写实现细节，不把未实现行为写成已完成。术语与范围以节点 0.1–0.4 为准，本文不改写它们。

## 1. 形态

- 一个本地单体仓库（local monolith），在一台电脑上由一名用户使用。
- 一名用户：创作者本人，同时担任主编。
- 一个故事项目；仅中文；一个写作模型供应商；生成单位为场景。
- 候选变更必须经人类主编批准或拒绝后，才能提交 Canon。
- **自动批准不是 MVP 正常行为。**
- **多项目不是 MVP 正常行为。**

节点 1.1 提供目录与约定。节点 1.2 增加可启动的 Postgres 与仅含 `/healthz`、`/version` 的 FastAPI。节点 1.3 在其上增加请求关联、JSON 日志与审计写入框架。节点 2.1 增加唯一 Story Project 与 Story Spec 草稿 / 提交 / 人工批准 / 修订版本。节点 2.2 增加最小 Canon 读写。节点 2.3 增加 Canon Snapshot 冻结与回放查询。节点 3.1 增加 Scene Card 与场景依赖。节点 3.2 增加可替换 LLM Gateway（超时 / 退避 / 重试）与 Fake Provider。节点 3.3 增加 Scene Plan 作业（已批准且可生成的 Scene Card + 指定 Snapshot → 校验后的 Scene Plan）。节点 3.4 增加 Scene Draft 作业（已批准 Scene Card + 有效 Scene Plan + Snapshot + 预冻结 Context Pack 引用 → 不可变散文修订）。节点 4.1 增加 Candidate Change 抽取作业（已生成不可变 Scene Draft → 绑 Evidence 的候选变更；不写 Canon）。节点 4.2 增加人类批准 / 拒绝 / 提交（仅人工主编；提交才写 Canon）。节点 4.3 增加 Scene / Chapter 摘要作业（已有草稿 → 场景摘要；已有场景摘要 → 章摘要汇总；不写 Canon）。节点 5.1 增加 Validation Run（Extracted 候选 + Evidence + Canon / Snapshot + 已写定 Spec → Passed 只到 AwaitingVerdict；不写 Canon）。节点 5.2 增加 Repair Task（RuleFailed / Violation → 返工 → 必须再校验；不写 Canon）。节点 6.1 增加 Context Pack 组装器（已批准 Scene Card + 已写定 Spec + 冻结 Snapshot → 单场只读包；purpose 仅 Generate / Validate；不写 Canon）。节点 6.2 增加 Outline Revision（Drafting → Proposed → Confirmed；仅人工主编确认可用；确认不是批准，不写 Canon）。节点 7.1 增加版本化 Style Guide / Style Sample（仅人工主编批准 / 授权；批准不是 Canon 批准；冻结后须出新 Revision）。节点 7.2 增加 Style Validation v1（确定性风格检查 + Fake Provider；默认不阻断 Canon 提交）。节点 7.3 增加人类审校队列（仅人工主编裁决；候选 approve 复用 4.2，不 submit；不写 Canon）。节点 8.1 增加本地作业队列与 Worker（分发器，不是裁决者）。节点 8.2 增加 Agent 注册表与权限边界。节点 8.3 增加单场景 DAG 编排器。节点 8.4 增加批量项目/章调度（经 8.3 DAG + 8.1 Worker + 8.2 PermissionGuard；同项目仅依赖已批准的场景可入队；预算或连续失败则暂停并告警；dry-run 不调模型）。节点 9.1 增加 `evals/` 样本与确定性 runner。节点 9.2 增加实验运行与基线对比。节点 9.3 增加发布门与全书导出（只读检查；导出已批准草稿）。没有 10.x、真实模型客户端或用户鉴权。没有章级或全书级生成入口。

## 2. 目录边界

| 路径 | 本骨架中的角色 | 本节点不表示已经做成 |
| --- | --- | --- |
| `AGENTS.md` | 实现约定（八条规则） | 不表示业务已实现 |
| `docs/` | 已冻结范围 / 术语 / 状态机，以及本文与 `audit.md` | 不表示状态机已编码 |
| `docs/audit.md` | 审计表、JSON 日志与脱敏策略 | 不表示已有 7.2+ |
| `contracts/` | 已批准 JSON Schema（节点 0.4） | 不表示已有读写这些对象的服务 |
| `backend/` | FastAPI `/healthz`、`/version`、request_id / JSON 日志 / 审计写入，Story Project / Spec API，最小 Canon API，Canon Snapshot 冻结 / 回放，Scene Card / 顺序 / 依赖，LLM Gateway（Fake Provider），Scene Plan / Scene Draft 生成作业，Candidate Change 抽取作业，候选变更的人类批准 / 拒绝 / 提交，Scene / Chapter 摘要作业，Validation Run，Repair Task，Context Pack 组装器，Outline Revision，Style Guide / Style Sample，Style Validation，人类审校队列，本地作业队列 / Worker，Agent 注册表 / 权限，单场景 DAG 编排，批量调度（经 DAG / Worker / PermissionGuard），9.1 评测 runner（`slove_context/evals/`），9.2 实验运行（`slove_context/experiments/`），以及 9.3 发布门 / 全书导出（`slove_context/release/`） | 无用户鉴权 / 10.x / 真实模型客户端；无章级 / 全书级生成；单元测试用内存仓库，不连库 |
| `evals/` | 节点 9.1 叙事一致性评测：`cases/` 清单、`fixtures/` 合同载荷、`expected/` 期望候选与违规 | 9.2 只读引用该钉死案例集，不得改写 expected；不是 9.3 发布门；runner / 实验均不写 Canon |
| `backend/alembic/` | `audit_events`、Story Project / Spec 与 Canon 表的可审阅迁移；2.3 增量加 snapshot 列；3.1 建 `arcs` / `chapters` / `scenes` / `scene_dependencies`；3.3 建 `scene_plan_jobs` / `scene_plans`；3.4 建 `scene_draft_jobs` / `scene_drafts`；4.1 建 `extract_jobs` / `candidate_changes`；4.2 在 `candidate_changes` 上增量加批准 / 提交列；4.3 建 `summary_jobs` / `scene_summaries` / `chapter_summaries`；5.1 建 `validation_runs` / `validation_reports`；5.2 建 `repair_tasks`；6.1 建 `context_packs`；6.2 建 `outline_revisions`；7.1 建 `style_guides` / `style_samples` 并在 `scene_drafts` 上增量加风格引用列；7.2 建 `style_validations`；7.3 建 `review_queue_items` / `review_decisions`；8.1 建 `jobs` / `job_payloads` / `job_locks`；8.2 建 `agents` / `agent_runs`；8.3 建 `scene_dags` / `dag_nodes`；8.4 建 `project_schedule_configs` / `schedule_runs` / `schedule_decisions` / `schedule_alerts` / `schedule_budget_counters`；9.2 建 `experiments` / `experiment_runs` / `experiment_comparisons`；9.3 建 `release_checks` / `release_manifests` / `release_exports` / `release_due_items` / `release_waivers` / `release_safety_checks` | 单元测试不跑迁移；不重建 Canon / 项目 / Scene Card / Scene Plan / Scene Draft / extract / 摘要 / Validation Run / Repair Task / Context Pack / Outline / Style Guide / Style Validation / 审校队列 / jobs / Agent / DAG / 调度 / 实验表；不建章级生成 / 10.x |
| `prompts/` | 带版本号的 Scene Plan / Scene Draft / Candidate Extract / Scene Summary / Chapter Summary / Style Validation Prompt 模板 | 不是 Context Pack 组装 Prompt，也不是 5.x Validate Prompt |
| `tests/` | `/healthz`、request_id、审计写入、Story Project / Spec、Canon、Snapshot、Scene Card、LLM Gateway、Scene Plan / Scene Draft 作业、Candidate Change 抽取与人类批准 / 提交、Scene / Chapter 摘要、Validation Run、Repair Task、Context Pack 组装、Outline Revision、Style Guide / Style Sample、Style Validation、审校队列、本地作业队列 / Worker、Agent 注册表 / 权限、单场景 DAG 编排、批量调度、叙事一致性评测、实验运行与基线对比、发布门与全书导出的进程内测试；可收集 `contracts/` 测试 | 不需要 live Postgres；无真实模型调用；Gateway / 作业 / 评测 / 实验 / 发布测试只用 Fake / 夹具 |
| `scripts/` | 脚本目录占位 | 无业务命令 |
| `data/` | 本地数据目录占位 | 不存放密钥、正文敏感内容或模型输出（见 `.gitignore`） |
| `docker-compose.yml` | 可启动的 Postgres（healthcheck + 持久卷） | 无 backend 容器（可选） |
| `.env.example` | 变量名与安全注释 | 不读取、不连接、不含真实密钥 |
| `Makefile` | `install` / `format` / `lint` / `typecheck` / `test` | 不启动服务 |

## 3. 本仓库包含（节点 1.1 + 1.2 + 1.3 + 2.1 + 2.2 + 2.3 + 3.1 + 3.2 + 3.3 + 3.4 + 4.1 + 4.2 + 4.3 + 5.1 + 5.2 + 6.1 + 6.2 + 7.1 + 7.2 + 7.3 + 8.1 + 8.2 + 8.3 + 8.4 + 9.1 + 9.2 + 9.3）

- 仓库根约定：`AGENTS.md`、`.gitignore`、`.env.example`、`Makefile`。
- 目录占位：`backend/`、`tests/`、`scripts/`、`data/`、`prompts/`。
- 边界说明：本文；脱敏与审计说明：`docs/audit.md`。
- 编排：`docker-compose.yml` 启动 Postgres（healthcheck + 命名卷）。
- FastAPI：`GET /healthz` 与 `GET /version`（保留）；请求中间件补 `request_id` 与 JSON 请求完成日志。
- 通用 `AuditWriter` + `AuditSink`（测试用内存 sink）。写操作走该路径。
- Alembic：`audit_events`（1.3）、`story_projects` / `story_specs` / `story_spec_versions`（2.1），`entities` / `evidence_records` / `canon_facts` / `canon_fact_versions` / `canon_snapshots`（2.2），`canon_snapshots` 增量列（2.3），`arcs` / `chapters` / `scenes` / `scene_dependencies`（3.1），`scene_plan_jobs` / `scene_plans`（3.3），`scene_draft_jobs` / `scene_drafts`（3.4），`extract_jobs` / `candidate_changes`（4.1；并允许草稿状态 `Extracted`），`candidate_changes` 批准裁决 / 提交事实引用列（4.2），`summary_jobs` / `scene_summaries` / `chapter_summaries`（4.3），`validation_runs` / `validation_reports`（5.1；违规嵌入报告 JSON），`repair_tasks`（5.2），`context_packs`（6.1），`outline_revisions`（6.2），`style_guides` / `style_samples` 与 `scene_drafts` 风格引用列（7.1），`style_validations`（7.2），`review_queue_items` / `review_decisions`（7.3），`jobs` / `job_payloads` / `job_locks`（8.1），`agents` / `agent_runs`（8.2），`scene_dags` / `dag_nodes`（8.3），`project_schedule_configs` / `schedule_runs` / `schedule_decisions` / `schedule_alerts` / `schedule_budget_counters`（8.4），`experiments` / `experiment_runs` / `experiment_comparisons`（9.2），以及 `release_checks` / `release_manifests` / `release_exports` / `release_due_items` / `release_waivers` / `release_safety_checks`（9.3）手写迁移。
- Story Project / Story Spec API：创建唯一项目、创建草稿、读取、提交写定、仅人工主编批准、列 Revision、批准后以新草稿 Revision 改写。对照 `contracts/story-spec.schema.json`。
- 最小 Canon API：通用实体、证据、Canon 事实创建（NotInCanon）、仅人工主编批准 / 废弃 / supersede、按项目 / 实体 / 谓语 / 故事时间查询生效的 Active 事实。事实只追加，禁止就地改 Active 正文。
- Canon Snapshot API：按场景序号和/或故事时间创建快照并捕获当时可见的 Active 事实；仅人工主编冻结；按 snapshot_id 查询；两快照 diff（稳定排序）；回放查询。快照不代替当前 Canon。
- Scene Card API：创建卷或弧 / 章（结构容器）与场景草稿 + Scene Card；仅草稿可 PATCH；仅人工主编批准；设置 / 查询依赖；按故事顺序列出；查询可生成场景。对照 `contracts/scene-card.schema.json`。可生成是派生标志，不是已生成草稿。
- LLM Gateway：`Provider.generate_text` / `generate_structured`；v1 仅 Fake Provider + 夹具；超时、指数退避、可配置 max retries。只对无持久化副作用的幂等 generate_* 重试。日志复用 1.3 脱敏。不写 Canon。
- Scene Plan 作业：已批准且可生成的 Scene Card + 指定 Canon Snapshot；对照 `contracts/scene-plan.schema.json`；`prompts/scene_plan.v1.md`；schema 失败至多一次 format repair；失败保留证据。作业不写 Canon。
- Scene Draft 作业：已批准且可生成的 Scene Card + 有效 Scene Plan + 指定 Snapshot + 预冻结 Context Pack 引用；`prompts/scene_draft.v1.md`；不可变修订版本；至多 Generated（抽取成功后可到 Extracted）；不自动批准、不写 Canon。
- Candidate Change 抽取作业：已生成且不可变的 Scene Draft；`prompts/extract_candidates.v1.md`；对照 `contracts/candidate-change.schema.json`；每条绑定 Evidence；初始状态仅 Extracted；schema 失败至多一次 format repair；追加抽取批次；抽取不写 Canon、不批准、不做 Validate。
- Candidate Change 人类批准 / 提交：对照 `contracts/approval-decision.schema.json`；仅人工主编；Approve 只记录裁决；Reject 不写 Canon；Submit 才创建或 supersede Canon Fact；候选不变成事实；无自动批准。
- Scene / Chapter 摘要作业：Scene Summary 基于已有不可变 Scene Draft 修订（revision id + content hash）；Chapter Summary 由该章已有 Scene Summary 汇总，不是一次生成整章散文；`prompts/scene_summary.v1.md` / `prompts/chapter_summary.v1.md`；修订不可变；不写 Canon、不自动批准、不当作 Candidate Change。
- Validation Run：已抽取且绑 Evidence 的候选 + 当前 Canon 或指定 Snapshot + 已写定 / 生效 Story Spec；确定性规则（Active 事实冲突、规格 forbid-list）；对照 `contracts/validation-report.schema.json`。Passed 只把候选送到 AwaitingVerdict。RuleFailed / ExecFailed 不得进入批准。作业不写 Canon。无自动批准。
- Repair Task：仅从 RuleFailed Validation Report / Violation 开立；完成后必须再跑 5.1 Validation Run；RecheckPassed 不是批准，不写 Canon。HumanReject 拒绝 FailedValidation 候选且不写 Canon；无新抽取时再校验为 N/A。可调用既有 3.3 / 3.4 / 4.1 作业。无整章散文生成。
- Context Pack 组装器：已批准 Scene Card + 已写定 / 生效 Story Spec + 冻结 Canon Snapshot + 唯一场景；对照 `contracts/context-pack.schema.json`；purpose 仅 Generate / Validate；`canon_excerpts` 是指定 Snapshot 的只读摘录；冻结后不可变，再组装出新 Revision；确定性复制 / 过滤，无 LLM。包不是 Canon，不批准、不提交、不抽取。3.4 Scene Draft 仍接受静态夹具 id 或已冻结组装包。无章级 / 全书级包。
- Outline Revision：拟定（Drafting）→ 提交确认（Proposed）→ 仅人工主编确认可用（Confirmed）。确认可用不是 Approval，不写 Canon。已确认版本只读；结构改动出新 Revision / 新 id（Revising → Proposed → Confirmed）；旧 Confirmed 可变为 Superseded。层次 Story → Arc/Volume → Chapter → Scene，场景节点引用已有 3.1 Scene。大纲不是生成单位。无章级 / 全书级生成入口。失败 / 取消保留记录。
- Style Guide / Style Sample：创建草稿；仅人工主编批准 Guide 或授权 Sample；批准 / 授权后冻结，改动出新 Revision / 新 id。使用风格只能引用已批准 Guide 与已授权 Sample。Scene Draft 可关联所用 Guide 修订（仅引用，不改 3.4 生成作业）。批准风格资产不是 Canon 批准，不写 Canon。审计不存正例 / 反例 / 样本正文。
- Style Validation：对一场不可变 Scene Draft 跑确定性风格检查（人称、时态标记、禁用词、超长句比例、段落长度、对话比例、重复 n-gram）以及可选 Fake Provider LLM 检查（只对照已批准 Style Guide）。未批准 Guide / 未授权 Sample 不得引用。禁止在世作家仿写评分。无 Guide 时 LLM 检查显式跳过或拒绝。报告含 problem / evidence / severity / minimal fix 与 rule / score 版本。`blocks_canon_submit` 默认 false。不是 5.x Validation Run，不改硬规则，不写 Canon，不阻断 Canon 提交。审计不存正例 / 反例 / 样本正文 / 草稿散文。
- 人类审校队列：按 type+id 入队已有 Scene Plan / Scene Draft / Candidate Change / Validation Report / Repair Task / Style Report。仅人工主编可 approve / reject / request_revision / escalate，每步必须有 reason_code。队列项含 input versions、Context Pack 引用、evidence refs、diff、decision history；可按 blocker / 项目 / 章 / 状态筛选排序。可导出 JSON review pack。候选变更的队列 approve 复用 4.2 approve（AwaitingVerdict → Approved），不 submit；提交 Canon 仍走既有 `POST .../submit`。批准 Style Report 不是 Canon 批准，默认不阻断 Canon 提交。失败 / 取消保留记录。无生产 seed-status。
- 本地作业队列 / Worker：入队 `job_type` + `payload_reference`；状态 queued / running / succeeded / failed / cancelled / dead_letter。Worker 按类型调用既有 plan / draft / extract / validate / repair / summarize / context_pack 服务。同场写作业经场景锁串行。支持幂等、超时、退避、max retries、dead-letter、人工 rerun、按保存输入引用重放。Worker 不批准 Candidate Change、不提交 Canon、不做审校队列裁决。失败 / 取消 / dead_letter 保留记录。可选进程内 `tick()` / `run_once()`。无生产 seed-status。
- Agent 注册表 / 权限：七类 Agent（Outline / Draft / Extractor / Consistency / Style / Repair / Human Approver）。每条记录含 input / output schema、allowed tools、forbidden operations、model config、prompt version、timeout、cost cap。服务层 `PermissionGuard` 再检查；未授权 403。Agent Run 归档 input_ref / output_ref / tool_calls / cost / duration / error，可回放。任何 Agent（含 Worker / system）不得绕过 Approval 写 Canon。Human Approver 是唯一 Canon 批准角色。提交 Canon 仍走 4.2。无生产 seed-status。
- 单场景 DAG 编排：固定节点 context_pack / scene_plan / plan_validation / scene_draft / candidate_extraction / draft_validation / human_review / canon_commit / summary / downstream_unblock。编排器管状态、输入、权限与批准；节点经 8.1 Worker / 8.2 权限无状态执行。并行节点不得写同一资源。blocker 停止后续自动 submit。按节点 rerun 默认复用冻结上游；重建 Context Pack 必须显式。可视化 JSON 含节点 status 与 duration_ms。canon_commit 仅在人类批准后调用既有 4.2 submit。无生产 seed-status。
- 批量调度：按项目配置并发 / 日 Token 预算 / 单场成本上限 / 连续失败阈值。多项目可同时推进。同项目仅 3.1 可生成场景（依赖已批准）可入队。禁止并行：有先后状态依赖的散文场、Canon 写入、同一 Snapshot 上的冲突 Canon 更新。预算超限或连续失败达阈值则自动暂停并开人类告警；恢复须人类触发。dry-run 只出执行计划与估计任务数，不调模型、不入队写作业、不写 Canon。调度走既有 DAG + Worker + PermissionGuard。无自动批准。无 9.x。无生产 seed-status。
- 叙事一致性评测（节点 9.1）：`evals/cases/`、`evals/fixtures/`、`evals/expected/` 与确定性 runner。九类一致性错误各至少一例。复用 5.x 硬规则；仅当类别无法用既有规则表达时才加 `eval.*` 检查。不写 Canon，不批准，不调真实模型。无评测 HTTP 路由。
- 实验运行与基线对比（节点 9.2）：钉死 9.1 案例集后可替换 model / prompt_version / retrieval_strategy / temperature / max_tokens；记录完整配置、输入版本、输出引用、六项指标、token 成本与延迟；可与基线 Run 对比并导出 CSV / JSON。历史 Run 只读；未冻结 Prompt 不得覆盖旧 Run。仅 Fake Provider。不写 Canon，不批准。不是 9.3 发布门。
- 发布门与全书导出（节点 9.3）：对已有已批准草稿 / Validation / 候选提交或拒绝 / 冻结 Snapshot / 章摘要 / 风格校验 / 审计做八项只读预发布检查。全部通过才写不可变 Release Manifest 并允许正式导出（Markdown / JSON / 审校包）。任一失败返回机器可读失败列表，禁止正式导出；失败检查记录可保留，但不是正式发布。伏笔到期项为最小 due-item + 人类豁免。安全检查为确定性占位或人类豁免，不调真实安全供应商。发布路径不批准、不提交 Canon，不自动发表草稿，不生成新散文。
- 进程内测试：`/healthz`、request_id、审计写入与脱敏、Story Project / Spec、Canon、Snapshot、Scene Card、LLM Gateway、Scene Plan / Scene Draft 作业、Candidate Change 抽取与人类批准 / 提交、Scene / Chapter 摘要、Validation Run、Repair Task、Context Pack 组装、Outline Revision、Style Guide / Style Sample、Style Validation、审校队列、本地作业队列 / Worker、Agent 注册表 / 权限、单场景 DAG、批量调度、叙事一致性评测、实验运行与基线对比、发布门与全书导出（以及已有的 contracts 校验）。不连 Postgres，不调用真实模型。

## 4. 本节点明确不是

下列项不属于节点 9.3，不得当作本节点已交付：

- 节点 10.x、真实模型客户端或用户鉴权。
- 把 Validate 通过写成批准，或自动 Approve / Submit / 写 Canon。
- 把摘要写成 Canon / Scene Draft / Candidate Change，或自动批准。
- 对 OpenAI / Anthropic 或其他供应商的真实 HTTP / SDK。
- 向量检索、图数据库。
- 「生成一整章」或全书级生成入口。
- 把角色 / 场景做成小说写作产品（实体只是通用对象；场景卡只规定一场的生成边界；计划只是一场意图；草稿只是一场散文）。
- 用户鉴权、队列。
- 自动批准、多项目、第二语言或第二模型供应商。
- 修改已批准的 `docs/mvp-scope.md`、`docs/domain-glossary.md`、`docs/state-machines.md` 或 `contracts/` 既有文件。
- 候选变更自动变成 Canon 事实。
- 批准 Scene Card 或生成 Scene Plan / Scene Draft 时写入 Canon。
- 用快照绕过人类批准去改当前 Canon。
- 网关或作业把生成结果写入 Canon 或自动批准。
- 草稿自动成为已批准或已发表。
- 候选变更自动进入 Approved / Submitted；Passed / RecheckPassed 只到 AwaitingVerdict，不是批准。
- 抽取作业把候选写成 Canon Fact，或改写 Scene Draft 正文。
- 把 Repair Task 完成或 RecheckPassed 写成批准或 Canon 写入。
- 把 Context Pack 冻结写成 Canon 批准，或把 Snapshot 摘录写回 Canon。
- 章级或全书级 Context Pack。
- 把 Outline 确认可用写成 Canon 批准，或用大纲覆盖 Canon。
- 把大纲当生成单位，一次生成整章或全书。
- 把 Style Guide / Sample 批准写成 Canon 批准，或在批准风格资产时写 Canon。
- 把 Style Validation 发现默认写成 Canon 提交阻断，或改 5.x Validation Run 硬规则。
- 在世作家仿写评分。
- 把审校队列 approve 写成 Canon 提交，或把 Style Report 批准写成 Canon 批准。
- 把 Worker 写成裁决者：自动批准 Candidate Change、自动提交 Canon、或代替人类做审校队列裁决。
- 把 Agent 写成可绕过 Approval 写 Canon，或让非 Human Approver 批准 Canon。
- 把 DAG 编排器写成可自动批准或自动提交 Canon。
- 把批量调度写成可自动批准或自动提交 Canon，或绕过 PermissionGuard / 人类 Canon 门。
- 改写 3.4 Scene Draft 生成作业 / Fake Provider Prompt（仅允许草稿上关联已批准 Guide 修订作为引用）。
- 把 9.1 评测 runner 写成会写 Canon、自动批准、调用真实模型，或改 5.x 硬规则语义。
- 把 9.2 实验运行写成会写 Canon、自动批准、调用真实模型，或改写 9.1 expected 答案。
- 把 9.2 实验对比写成 9.3 发布门或全书导出。
- 把 9.3 发布检查写成会写 Canon、自动批准、调用真实模型或真实安全供应商，或改写 9.1 expected / 9.2 历史 Run。
- 把正式导出写成章级或全书级生成入口。

## 5. 与已冻结文档的关系

实现必须服从：

- `docs/mvp-scope.md`（节点 0.1）
- `docs/domain-glossary.md`（节点 0.2）
- `docs/state-machines.md`（节点 0.3）
- `contracts/`（节点 0.4）

本文只画仓库边界，不重复定义术语，不把 Schema 对象写成已经落地的服务。
