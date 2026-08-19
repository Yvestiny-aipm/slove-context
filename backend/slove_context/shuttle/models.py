"""Constants for the human shuttle (nodes UI.2 / UI.3)."""

from __future__ import annotations

PURPOSE_SCENE_DRAFT = "scene_draft"
PURPOSE_EXTRACT = "extract"
PURPOSE_SCENE_SUMMARY = "scene_summary"
PURPOSE_CHAPTER_SUMMARY = "chapter_summary"

SHUTTLE_DRAFT_PROMPT_VERSION = "scene_draft.shuttle.v1"
SHUTTLE_EXTRACT_PROMPT_VERSION = "extract_candidates.shuttle.v1"
SHUTTLE_SCENE_SUMMARY_PROMPT_VERSION = "scene_summary.shuttle.v1"
SHUTTLE_CHAPTER_SUMMARY_PROMPT_VERSION = "chapter_summary.shuttle.v1"
EXTERNAL_SUBSCRIBED_MODEL = "external-subscribed"

MIN_DRAFT_BODY_CHARS = 50
MIN_SCENE_SUMMARY_BODY_CHARS = 40
