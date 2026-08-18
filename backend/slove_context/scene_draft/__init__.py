"""Scene Draft generation jobs (node 3.4).

Input: approved generatable Scene Card + valid Scene Plan + Canon Snapshot
id + a pre-frozen Context Pack reference. Output: immutable Scene Draft
prose (Generated at most). Retry creates a new revision.

Fake Provider only. Does not write Canon. Does not auto-approve.
Does not extract Candidate Changes (node 4.1). No Context Pack builder.
"""
