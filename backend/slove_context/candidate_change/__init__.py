"""Candidate Change extraction jobs (node 4.1).

Input: one generated immutable Scene Draft (status at least Generated),
its Scene, and project. Output: candidates that validate against
contracts/candidate-change.schema.json. Each binds Evidence.

Candidate Change is not Canon Fact. Jobs use the Fake Provider only.
One format-repair attempt. Initial status is Extracted only.
No Validate (4.2). No approve / submit. No Scene Draft overwrite.
"""
