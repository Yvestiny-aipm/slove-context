export const ACTOR_TYPE = "human_editor";
export const ACTOR_ID = "editor-1";

export const ACTOR_HEADERS: Record<string, string> = {
  "X-Actor-Type": ACTOR_TYPE,
  "X-Actor-Id": ACTOR_ID,
  "Content-Type": "application/json",
};

export function apiBase(): string {
  return import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
}

export function reviewApprovePath(projectId: string, itemId: string): string {
  return `/projects/${projectId}/review-queue/${itemId}/approve`;
}

export function reviewRejectPath(projectId: string, itemId: string): string {
  return `/projects/${projectId}/review-queue/${itemId}/reject`;
}

export function candidateSubmitPath(
  projectId: string,
  candidateId: string,
): string {
  return `/projects/${projectId}/candidate-changes/${candidateId}/submit`;
}

export function candidateApprovePath(
  projectId: string,
  candidateId: string,
): string {
  return `/projects/${projectId}/candidate-changes/${candidateId}/approve`;
}

export function shuttleDraftPromptPath(
  projectId: string,
  sceneId: string,
): string {
  return `/projects/${projectId}/scenes/${sceneId}/shuttle/draft-prompt`;
}

export function shuttleDraftsPath(projectId: string, sceneId: string): string {
  return `/projects/${projectId}/scenes/${sceneId}/shuttle/drafts`;
}

export function shuttleExtractPromptPath(
  projectId: string,
  sceneId: string,
  revisionId: string,
): string {
  return `/projects/${projectId}/scenes/${sceneId}/drafts/${revisionId}/shuttle/extract-prompt`;
}

export function shuttleExtractsPath(
  projectId: string,
  sceneId: string,
  revisionId: string,
): string {
  return `/projects/${projectId}/scenes/${sceneId}/drafts/${revisionId}/shuttle/extracts`;
}

export function shuttleSceneSummaryPromptPath(
  projectId: string,
  sceneId: string,
  draftRevisionId: string,
): string {
  const query = new URLSearchParams({
    draft_revision_id: draftRevisionId,
  });
  return `/projects/${projectId}/scenes/${sceneId}/shuttle/summary-prompt?${query.toString()}`;
}

export function shuttleSceneSummariesPath(
  projectId: string,
  sceneId: string,
): string {
  return `/projects/${projectId}/scenes/${sceneId}/shuttle/summaries`;
}

export function fakeDraftJobsPath(projectId: string, sceneId: string): string {
  return `/projects/${projectId}/scenes/${sceneId}/drafts/jobs`;
}

export function fakeExtractJobsPath(
  projectId: string,
  sceneId: string,
  revisionId: string,
): string {
  return `/projects/${projectId}/scenes/${sceneId}/drafts/${revisionId}/extract-jobs`;
}

export function fakeSceneSummaryJobsPath(
  projectId: string,
  sceneId: string,
): string {
  return `/projects/${projectId}/scenes/${sceneId}/summaries/jobs`;
}

async function parse(response: Response): Promise<unknown> {
  const text = await response.text();
  const body = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(
      `${response.status} ${response.statusText}: ${text.slice(0, 400)}`,
    );
  }
  return body;
}

export async function apiGet(path: string): Promise<unknown> {
  const response = await fetch(`${apiBase()}${path}`, {
    headers: ACTOR_HEADERS,
  });
  return parse(response);
}

export async function apiPost(
  path: string,
  body: Record<string, unknown> = {},
): Promise<unknown> {
  const response = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers: ACTOR_HEADERS,
    body: JSON.stringify(body),
  });
  return parse(response);
}

export async function approveReviewItem(
  projectId: string,
  itemId: string,
  reasonCode = "editorial_ok",
): Promise<unknown> {
  return apiPost(reviewApprovePath(projectId, itemId), {
    reason_code: reasonCode,
    created_by: "主编",
  });
}

export async function rejectReviewItem(
  projectId: string,
  itemId: string,
  reasonCode = "editorial_reject",
): Promise<unknown> {
  return apiPost(reviewRejectPath(projectId, itemId), {
    reason_code: reasonCode,
    created_by: "主编",
  });
}

export async function submitCandidate(
  projectId: string,
  candidateId: string,
): Promise<unknown> {
  return apiPost(candidateSubmitPath(projectId, candidateId), {
    created_by: "主编",
  });
}

export type JsonRecord = Record<string, unknown>;

export function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

export function asList(value: unknown): JsonRecord[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is JsonRecord =>
      Boolean(item) && typeof item === "object" && !Array.isArray(item),
  );
}

export function textOf(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}
