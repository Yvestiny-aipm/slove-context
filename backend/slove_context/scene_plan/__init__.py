"""Scene Plan generation jobs (node 3.3).

Input: an approved, generatable Scene Card and a specified Canon Snapshot.
Output: a Scene Plan that validates against contracts/scene-plan.schema.json.

Scene Plan is intent, not Canon and not Scene Draft. Jobs use the Fake
Provider only. One format-repair attempt. No Scene Draft generation
(node 3.4). No live vendor HTTP. Jobs do not write Canon.
"""
