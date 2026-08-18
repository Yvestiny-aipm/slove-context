"""Local job queue and Worker (node 8.1).

The Worker is a dispatcher only. It calls existing plan / draft /
extract / validate / repair / summarize / context_pack services.
It does not approve Candidate Changes, does not submit Canon, and
does not take human review-queue decisions. No Agent registry (8.2),
DAG (8.3), or batch (8.4).
"""
