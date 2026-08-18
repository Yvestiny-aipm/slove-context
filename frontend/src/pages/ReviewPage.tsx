import { useEffect, useState } from "react";
import {
  ACTOR_ID,
  ACTOR_TYPE,
  apiGet,
  approveReviewItem,
  asList,
  asRecord,
  rejectReviewItem,
  submitCandidate,
  textOf,
} from "../api";

export function ReviewPage({ projectId }: { projectId: string }) {
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [items, setItems] = useState<Record<string, unknown>[]>([]);

  async function reload() {
    const body = asRecord(await apiGet(`/projects/${projectId}/review-queue`));
    setItems(asList(body.items));
  }

  useEffect(() => {
    let cancelled = false;
    reload()
      .catch((err: unknown) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function onApprove(itemId: string) {
    setError("");
    setMessage("");
    try {
      await approveReviewItem(projectId, itemId);
      setMessage("已批准（未提交 Canon）");
      await reload();
    } catch (err) {
      setError(String(err));
    }
  }

  async function onReject(itemId: string) {
    setError("");
    setMessage("");
    try {
      await rejectReviewItem(projectId, itemId);
      setMessage("已拒绝（未写 Canon）");
      await reload();
    } catch (err) {
      setError(String(err));
    }
  }

  async function onSubmit(candidateId: string) {
    setError("");
    setMessage("");
    try {
      await submitCandidate(projectId, candidateId);
      setMessage("已提交 Canon（单独动作）");
      await reload();
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <section>
      <h2>审校队列</h2>
      <p className="muted">
        批准走 7.3 / 4.2 裁决，不自动 submit。提交 Canon 是单独按钮，仅{" "}
        {ACTOR_ID} / {ACTOR_TYPE}。
      </p>
      {error ? <p className="error">{error}</p> : null}
      {message ? <p>{message}</p> : null}
      {items.map((item) => {
        const itemId = textOf(item.id);
        const subjectType = textOf(item.subject_type);
        const subjectId = textOf(item.subject_id);
        return (
          <div key={itemId} className="card">
            <p>对象：{subjectType} / {subjectId}</p>
            <p>队列状态：{textOf(item.status)}</p>
            <div className="actions">
              <button type="button" onClick={() => void onApprove(itemId)}>
                批准
              </button>
              <button type="button" onClick={() => void onReject(itemId)}>
                拒绝
              </button>
              {subjectType === "candidate_change" ? (
                <button type="button" onClick={() => void onSubmit(subjectId)}>
                  提交 Canon
                </button>
              ) : null}
            </div>
          </div>
        );
      })}
    </section>
  );
}
