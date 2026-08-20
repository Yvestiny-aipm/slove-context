import { useEffect, useState } from "react";
import {
  apiGet,
  apiPost,
  asList,
  asRecord,
  DEEPSEEK_PROVIDER,
  draftJobsPath,
  shuttleDraftPromptPath,
  shuttleDraftsPath,
  shuttleExtractPromptPath,
  shuttleExtractsPath,
  shuttleSceneSummariesPath,
  shuttleSceneSummaryPromptPath,
  STATIC_CONTEXT_PACK_ID,
  textOf,
} from "../api";

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  throw new Error("clipboard unavailable");
}

function snapshotFrom(
  plan: Record<string, unknown>,
  drafts: Record<string, unknown>[],
): string {
  const fromPlan = textOf(plan.snapshot_id);
  if (fromPlan) return fromPlan;
  const first = drafts[0];
  if (!first) return "";
  return textOf(asRecord(first.input_versions).snapshot_id);
}

export function ScenePage({ projectId }: { projectId: string }) {
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [scenes, setScenes] = useState<Record<string, unknown>[]>([]);
  const [selected, setSelected] = useState("");
  const [plan, setPlan] = useState<Record<string, unknown>>({});
  const [drafts, setDrafts] = useState<Record<string, unknown>[]>([]);
  const [candidates, setCandidates] = useState<Record<string, unknown>[]>([]);
  const [summaries, setSummaries] = useState<Record<string, unknown>[]>([]);
  const [draftPaste, setDraftPaste] = useState("");
  const [extractPaste, setExtractPaste] = useState("");
  const [summaryPaste, setSummaryPaste] = useState("");
  const [reloadToken, setReloadToken] = useState(0);

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
  }, [projectId, selected, reloadToken]);

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
        let nextSummaries: Record<string, unknown>[] = [];
        try {
          nextSummaries = asList(
            asRecord(
              await apiGet(
                `/projects/${projectId}/scenes/${selected}/summaries`,
              ),
            ).items,
          );
        } catch {
          nextSummaries = [];
        }
        if (!cancelled) {
          setPlan(nextPlan);
          setDrafts(nextDrafts);
          setCandidates(nextCandidates);
          setSummaries(nextSummaries);
        }
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId, selected, reloadToken]);

  const scene = scenes.find((item) => textOf(item.id) === selected) ?? {};
  const planBody = asRecord(plan.plan);
  const currentDraft = drafts[0];
  const currentDraftId = textOf(currentDraft?.id);

  async function copyDraftPrompt() {
    if (!selected) return;
    try {
      const payload = asRecord(
        await apiGet(shuttleDraftPromptPath(projectId, selected)),
      );
      await copyText(textOf(payload.prompt));
      setFeedback("已复制写稿提示词");
      setError("");
    } catch (err) {
      setError(String(err));
    }
  }

  async function pasteDraft() {
    if (!selected) return;
    const snapshotId = snapshotFrom(plan, drafts);
    if (!snapshotId) {
      setError("缺少 snapshot_id，无法贴回正文");
      return;
    }
    try {
      await apiPost(shuttleDraftsPath(projectId, selected), {
        body: draftPaste,
        snapshot_id: snapshotId,
        plan_id: textOf(planBody.id) || undefined,
      });
      setDraftPaste("");
      setFeedback("已贴回正文（未批准，未写 Canon）");
      setError("");
      setReloadToken((value) => value + 1);
    } catch (err) {
      setError(String(err));
    }
  }

  async function copyExtractPrompt() {
    if (!selected || !currentDraftId) {
      setError("没有可抽取的草稿修订");
      return;
    }
    try {
      const payload = asRecord(
        await apiGet(
          shuttleExtractPromptPath(projectId, selected, currentDraftId),
        ),
      );
      await copyText(textOf(payload.prompt));
      setFeedback("已复制抽取提示词");
      setError("");
    } catch (err) {
      setError(String(err));
    }
  }

  async function pasteExtract() {
    if (!selected || !currentDraftId) {
      setError("没有可抽取的草稿修订");
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(extractPaste);
    } catch {
      setError("贴回抽取需要 JSON 数组");
      return;
    }
    const candidatesBody = Array.isArray(parsed)
      ? parsed
      : asList(asRecord(parsed).candidates);
    try {
      await apiPost(shuttleExtractsPath(projectId, selected, currentDraftId), {
        candidates: candidatesBody,
      });
      setExtractPaste("");
      setFeedback("已贴回抽取（Extracted，未批准，未写 Canon）");
      setError("");
      setReloadToken((value) => value + 1);
    } catch (err) {
      setError(String(err));
    }
  }

  async function copySummaryPrompt() {
    if (!selected || !currentDraftId) {
      setError("没有可摘要的草稿修订");
      return;
    }
    try {
      const payload = asRecord(
        await apiGet(
          shuttleSceneSummaryPromptPath(projectId, selected, currentDraftId),
        ),
      );
      await copyText(textOf(payload.prompt));
      setFeedback("已复制本场摘要提示词");
      setError("");
    } catch (err) {
      setError(String(err));
    }
  }

  async function generateDeepSeekDraft() {
    if (!selected) return;
    const snapshotId = snapshotFrom(plan, drafts);
    const planId = textOf(planBody.id);
    if (!snapshotId || !planId) {
      setError("缺少已批准 Scene Plan / snapshot，无法用 DeepSeek 生成本场");
      return;
    }
    try {
      const payload = asRecord(
        await apiPost(draftJobsPath(projectId, selected), {
          snapshot_id: snapshotId,
          plan_id: planId,
          context_pack_id: STATIC_CONTEXT_PACK_ID,
          provider: DEEPSEEK_PROVIDER,
        }),
      );
      if (textOf(payload.state) === "failed") {
        setError(
          `DeepSeek 写稿失败：${textOf(payload.failure_reason) || "generate_failed"}`,
        );
        setFeedback("");
        return;
      }
      setFeedback("已用 DeepSeek 生成本场正文（未批准，未写 Canon）");
      setError("");
      setReloadToken((value) => value + 1);
    } catch (err) {
      setError(String(err));
    }
  }

  async function pasteSummary() {
    if (!selected || !currentDraftId) {
      setError("没有可摘要的草稿修订");
      return;
    }
    try {
      await apiPost(shuttleSceneSummariesPath(projectId, selected), {
        draft_revision_id: currentDraftId,
        body: summaryPaste,
      });
      setSummaryPaste("");
      setFeedback("已贴回本场摘要（未批准，未写 Canon）");
      setError("");
      setReloadToken((value) => value + 1);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <section>
      <h2>当前场景</h2>
      <p className="muted">
        可用 DeepSeek 直接生成本场正文，或拷提示词到你自己的模型再贴回。穿梭不经本仓库模型 API。
      </p>
      {error ? <p className="error">{error}</p> : null}
      {feedback ? <p className="muted">{feedback}</p> : null}
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
      <h3>DeepSeek 写稿</h3>
      <div className="card actions">
        <button type="button" onClick={() => void generateDeepSeekDraft()}>
          用 DeepSeek 生成本场正文
        </button>
        <p className="muted">走既有草稿作业。需要 DEEPSEEK_API_KEY。不批准，不写 Canon。</p>
      </div>
      <h3>人工穿梭</h3>
      <div className="card actions">
        <button type="button" onClick={() => void copyDraftPrompt()}>
          复制写稿提示词
        </button>
        <textarea
          value={draftPaste}
          onChange={(event) => setDraftPaste(event.target.value)}
          placeholder="把外部模型返回的正文贴在这里"
          rows={5}
        />
        <button type="button" onClick={() => void pasteDraft()}>
          贴回正文
        </button>
        <button type="button" onClick={() => void copyExtractPrompt()}>
          复制抽取提示词
        </button>
        <textarea
          value={extractPaste}
          onChange={(event) => setExtractPaste(event.target.value)}
          placeholder='贴回抽取（JSON 数组）'
          rows={5}
        />
        <button type="button" onClick={() => void pasteExtract()}>
          贴回抽取（JSON 数组）
        </button>
        <button type="button" onClick={() => void copySummaryPrompt()}>
          复制本场摘要提示词
        </button>
        <textarea
          value={summaryPaste}
          onChange={(event) => setSummaryPaste(event.target.value)}
          placeholder="把外部模型返回的本场摘要贴在这里"
          rows={4}
        />
        <button type="button" onClick={() => void pasteSummary()}>
          贴回本场摘要
        </button>
      </div>
      <h3>Scene Plan</h3>
      <pre>{planBody.id ? JSON.stringify(planBody, null, 2) : "尚无计划"}</pre>
      <h3>Scene Draft</h3>
      {drafts.map((draft) => (
        <div key={textOf(draft.id)} className="card">
          <p>修订 {textOf(draft.revision)} / {textOf(draft.status)}</p>
          <pre>{textOf(draft.body)}</pre>
        </div>
      ))}
      <h3>本场摘要</h3>
      {summaries.length === 0 ? <p className="muted">尚无摘要</p> : null}
      {summaries.map((item) => (
        <div key={textOf(item.id)} className="card">
          <p>
            修订 {textOf(item.revision)} / {textOf(item.status)} /{" "}
            {textOf(item.generation_model)}
          </p>
          <pre>{textOf(item.body)}</pre>
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
