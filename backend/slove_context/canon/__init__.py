"""Minimal Canon data model and API (node 2.2).

Entities, evidence, and Canon Facts. Facts are append-only: corrections
supersede; in-place edits of an Active fact body are forbidden.
Approving or abandoning a fact is a human-editor action only.
Evidence is not Canon. This node does not freeze snapshots or replay them.
"""
