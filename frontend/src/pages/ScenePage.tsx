import { useEffect, useState } from "react";
import { apiGet, asList, asRecord, textOf } from "../api";

export function ScenePage({ projectId }: { projectId: string }) {
  const [error, setError] = useState("");
  const [scenes, setScenes] = useState<Record<string, unknown>[]>([]);
  const [selected, setSelected] = useState("");
  const [plan, setPlan] = useState<Record<string, unknown>>({});
  const [drafts, setDrafts] = useState<Record<string, unknown>[]>([]);
  const [candidates, setCandidates] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const nextScenes = asList(
          asRecord(await apiGet(`/projects/${projectId}/scenes`)).scenes,
        );
        if (!cancelled) {
          setScenes(nextScenes);
          if (!selected && nextScenes[0]) {
            setSelected(textOf(nextScenes[0].id));
          }
        }
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId, selected]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    async function load() {
      try {
        let nextPlan: Record<string, unknown> = {};
        try {
          nextPlan = asRecord(
            await apiGet(
              `/projects/${projectId}/scenes/${selected}/plans/current`,
            ),
          );
        } catch {
          nextPlan = {};
        }
        const nextDrafts = asList(
          asRecord(
            await apiGet(`/projects/${projectId}/scenes/${selected}/drafts`),
          ).items,
        );
        const nextCandidates = asList(
          asRecord(
            await apiGet(
              `/projects/${projectId}/scenes/${selected}/candidate-changes`,
            ),
          ).items,
        );
        if (!cancelled) {
          setPlan(nextPlan);
          setDrafts(nextDrafts);
          setCandidates(nextCandidates);
        }
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId, selected]);

  const scene = scenes.find((item) => textOf(item.id) === selected) ?? {};
  const planBody = asRecord(plan.plan);

  return (
    <section>
      <h2>当前场景</h2>
      {error ? <p className="error">{error}</p> : null}
      <p>
        选择场景：
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          {scenes.map((item) => (
            <option key={textOf(item.id)} value={textOf(item.id)}>
              {textOf(item.story_order)} {textOf(item.location)}
            </option>
          ))}
        </select>
      </p>
      <h3>场景卡</h3>
      <div className="card">
        <p>POV：{textOf(scene.pov)}</p>
        <p>目标：{textOf(scene.goal)}</p>
        <p>冲突：{textOf(scene.conflict)}</p>
        <p>禁止：{JSON.stringify(scene.forbidden ?? [])}</p>
        <p>状态：{textOf(scene.status)} / 可生成：{scene.generatable ? "是" : "否"}</p>
      </div>
      <h3>Scene Plan</h3>
      <pre>{planBody.id ? JSON.stringify(planBody, null, 2) : "尚无计划"}</pre>
      <h3>Scene Draft（夹具散文）</h3>
      {drafts.map((draft) => (
        <div key={textOf(draft.id)} className="card">
          <p>修订 {textOf(draft.revision)} / {textOf(draft.status)}</p>
          <pre>{textOf(draft.body)}</pre>
        </div>
      ))}
      <h3>候选变更</h3>
      <table>
        <thead>
          <tr>
            <th>谓语</th>
            <th>状态</th>
            <th>证据</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((item) => (
            <tr key={textOf(item.id)}>
              <td>{textOf(item.predicate)}</td>
              <td>{textOf(item.status)}</td>
              <td>{textOf(item.evidence_quote)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
