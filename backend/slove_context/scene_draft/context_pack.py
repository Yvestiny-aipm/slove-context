"""Pre-frozen static Context Pack (node 3.4).

There is no Context Pack builder in this node. Jobs must reference the
fixture id below. Unknown or missing ids are rejected. The pack is
read-only context, not writable Canon.
"""

from __future__ import annotations

from typing import Any

# Well-known fixture id. Scene Draft jobs must send this exact value.
STATIC_CONTEXT_PACK_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

STATIC_CONTEXT_PACK: dict[str, Any] = {
    "schema_version": "0.4.0",
    "id": STATIC_CONTEXT_PACK_ID,
    "project_id": "11111111-1111-4111-8111-111111111111",
    "created_at": "2026-08-18T04:00:00Z",
    "created_by": "主编",
    "scene_id": "33333333-3333-4333-8333-333333333333",
    "purpose": "Generate",
    "story_spec_id": "22222222-2222-4222-8222-222222222222",
    "scene_card_id": "44444444-4444-4444-8444-444444444444",
    "knowledge_boundaries": ["林晚不知残玉能开门"],
    "canon_excerpts": [
        {
            "statement": "残玉只能由林晚触活",
            "source_evidence": "主编已批准并提交：残玉只能由林晚触活",
            "effective_story_time": "第一日拾玉之前",
        }
    ],
    "pre_frozen": True,
    "is_canon": False,
    "writable": False,
}


def get_static_context_pack(context_pack_id: str) -> dict[str, Any] | None:
    if context_pack_id == STATIC_CONTEXT_PACK_ID:
        return dict(STATIC_CONTEXT_PACK)
    return None
