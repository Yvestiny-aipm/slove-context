"""Agent Registry and permission boundaries (node 8.2).

Seven registered agents. The service layer re-checks permissions;
Prompt text is never trusted. Unauthorized tool calls are 403.

No Agent — including Worker / system — may bypass Approval to write
Canon. Only the Human Approver (human 主编) may approve Canon.
Canon write remains 4.2 human submit. No DAG (8.3). No batch (8.4).
No real model. Fake Provider / in-memory registry only.
"""
