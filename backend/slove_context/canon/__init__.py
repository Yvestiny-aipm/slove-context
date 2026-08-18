"""Minimal Canon data model and API (node 2.2 + 2.3).

Entities, evidence, and Canon Facts. Facts are append-only: corrections
supersede; in-place edits of an Active fact body are forbidden.
Approving or abandoning a fact is a human-editor action only.
Evidence is not Canon.

Node 2.3 adds Canon Snapshot create / freeze / query / diff / replay.
A snapshot is a read-only copy at a moment; it does not replace current
Canon. No Scene Card, Context Pack, generator, vector search, or LLM.
"""
