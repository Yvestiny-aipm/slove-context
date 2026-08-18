# Contracts（节点 0.4）

本目录只冻结 JSON Schema 契约。不启动 Phase 1 / 节点 1.1，不含数据库、API 或业务服务。

Schema 为 JSON Schema Draft 2020-12。术语对齐节点 0.2，状态枚举对齐节点 0.3。无自动批准字段；候选变更不能自动变成 Canon 事实。

## 运行校验

```bash
cd contracts
python3 -m pip install -r requirements.txt
pytest
```

也可在仓库根目录执行 `pytest contracts`（将发现 `contracts/tests`）。

每份 schema 在 `examples/` 下各有一份 valid 与一份 invalid 样例。测试断言：valid 必须通过，invalid 必须被拒绝。
