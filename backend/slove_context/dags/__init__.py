"""Single-scene DAG orchestrator (node 8.3).

The orchestrator owns state, inputs, permissions, and the human
approval gate. Nodes execute through the 8.1 Worker and 8.2
PermissionGuard. canon_commit calls existing 4.2 submit only after
a human 主编 approve. No 8.4 batch. No auto Canon approve.
"""
