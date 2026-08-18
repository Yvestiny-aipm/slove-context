"""Validation Run (node 5.1).

Deterministic Validate against current Canon (or a specified Snapshot)
and a written / effective Story Spec. Candidates must already be
Extracted and bind Evidence.

Passed moves candidates to AwaitingVerdict only. It is not Approval,
does not auto-approve, and does not write Canon. RuleFailed /
ExecFailed cannot enter approval. Failure and cancel keep records.

No Repair Task (node 5.2). No real model calls.
"""
