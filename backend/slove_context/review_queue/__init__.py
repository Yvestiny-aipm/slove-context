"""Human review-queue API (node 7.3).

Enqueue existing review subjects and record human decisions
(approve / reject / request_revision / escalate). Each decision
requires a reason_code. Only the human 主编 may decide.

Approving a Candidate Change reuses the 4.2 approve path
(AwaitingVerdict → Approved). It does not submit Canon. Canon commit
remains POST /projects/{project_id}/candidate-changes/{id}/submit.

Approving a Style Report is not Canon approval and does not block
Canon submit. No 8.x workers. No 9.x eval. No real model calls.
"""
