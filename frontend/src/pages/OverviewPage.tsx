import { useEffect, useState } from "react";
import { apiGet, asList, asRecord, textOf } from "../api";

const LOOP = [
  "规格",
  "Canon",
  "场景卡",
  "生成",
  "抽取",
  "校验",
  "人审",
  "写 Canon",
] as const;

function stuckStep(input: {
  specOk: boolean;
  snapshotOk: boolean;
  cardOk: boolean;
  draftOk: boolean;
  extracted: boolean;
  validated: boolean;
  awaiting: boolean;
  approved: boolean;
  submitted: boolean;
}): (typeof LOOP)[number] {
  if (!input.specOk) return "规格";
  if (!input.snapshotOk) return "Canon";
  if (!input.cardOk) return "场景卡";
  if (!input.draftOk) return "生成";
  if (!input.extracted) return "抽取";
  if (!input.validated && !input.awaiting && !input.approved && !input.submitted) {
    return "校验";
  }
  if (input.awaiting) return "人审";
  if (input.approved) return "写 Canon";
  return "写 Canon";
}

export function OverviewPage({ projectId }: { projectId: string }) {
  const [error, setError] = useState("");
  const [rows, setRows] = useState<
    Array<{ sceneId: string; title: string; step: string }>
  >([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const spec = asRecord(
          await apiGet(`/projects/${projectId}/specs/current`),
        );
        const scenes = asList(
          asRecord(await apiGet(`/projects/${projectId}/scenes`)).scenes,
        );
        const snapshots = asList(
          asRecord(await apiGet(`/projects/${projectId}/canon-snapshots`))
            .items,
        );
        const specOk = ["Effective", "Written"].includes(textOf(spec.status));
        const snapshotOk = snapshots.some(
          (item) => textOf(item.status) === "frozen",
        );
        const next: Array<{ sceneId: string; title: string; step: string }> =
          [];
        for (const scene of scenes) {
          const sceneId = textOf(scene.id);
          const drafts = asList(
            asRecord(
              await apiGet(`/projects/${projectId}/scenes/${sceneId}/drafts`),
            ).items,
          );
          const candidates = asList(
            asRecord(
              await apiGet(
                `/projects/${projectId}/scenes/${sceneId}/candidate-changes`,
              ),
            ).items,
          );
          const statuses = candidates.map((item) => textOf(item.status));
          const step = stuckStep({
            specOk,
            snapshotOk,
            cardOk: textOf(scene.status) === "approved",
            draftOk: drafts.length > 0,
            extracted: candidates.length > 0,
            validated: statuses.some((status) =>
              [
                "AwaitingVerdict",
                "Approved",
                "Submitted",
                "FailedValidation",
              ].includes(status),
            ),
            awaiting: statuses.includes("AwaitingVerdict"),
            approved: statuses.includes("Approved"),
            submitted: statuses.includes("Submitted"),
          });
          next.push({
            sceneId,
            title: `${textOf(scene.story_order)} ${textOf(scene.location)}`,
            step,
          });
        }
        if (!cancelled) setRows(next);
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return (
    <section>
      <h2>总览</h2>
      <p className="muted">
        场景闭环：规格 → Canon → 场景卡 → 生成 → 抽取 → 校验 → 人审 → 写
        Canon。批准不会自动提交 Canon。
      </p>
      {error ? <p className="error">{error}</p> : null}
      {rows.map((row) => (
        <div key={row.sceneId} className="card">
          <strong>{row.title}</strong>
          <div className="loop">
            {LOOP.map((step) => (
              <span
                key={step}
                className={step === row.step ? "step current" : "step"}
              >
                {step}
              </span>
            ))}
          </div>
          <p>当前卡在：{row.step}</p>
        </div>
      ))}
    </section>
  );
}
