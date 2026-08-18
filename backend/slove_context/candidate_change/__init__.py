"""Candidate Change extraction (4.1) and human verdicts (4.2).

Input: one generated immutable Scene Draft (status at least Generated),
its Scene, and project. Output: candidates that validate against
contracts/candidate-change.schema.json. Each binds Evidence.

Candidate Change is not Canon Fact. Extract jobs use the Fake Provider
only. One format-repair attempt. Initial status is Extracted only.

Node 4.2: only the human 主编 may approve, reject, or submit.
Approve does not write Canon. Submit creates or supersedes a Canon Fact.
No Validate / Validation Run. No Scene Draft overwrite.
"""
