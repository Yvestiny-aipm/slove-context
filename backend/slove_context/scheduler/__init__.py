"""Batch project/chapter scheduler (node 8.4).

Schedules scene DAGs through the existing 8.3 orchestrator, 8.1
Worker, and 8.2 PermissionGuard. Multi-project ticks are allowed.
Inside one project, only generatable scenes (3.1) may be enqueued.
Prose scenes with before/after state dependencies are serialized.
Canon writes are never parallel and never automatic.

This is not eval (9.x). No real model. No auto Canon approve.
Failed / cancelled / paused records are kept.
"""
