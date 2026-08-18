import { useEffect, useState } from "react";
import { apiGet, asList, asRecord, textOf } from "../api";

export function ProjectPage({ projectId }: { projectId: string }) {
  const [error, setError] = useState("");
  const [project, setProject] = useState<Record<string, unknown>>({});
  const [spec, setSpec] = useState<Record<string, unknown>>({});
  const [scenes, setScenes] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const nextProject = asRecord(await apiGet(`/projects/${projectId}`));
        const nextSpec = asRecord(
          await apiGet(`/projects/${projectId}/specs/current`),
        );
        const nextScenes = asList(
          asRecord(await apiGet(`/projects/${projectId}/scenes`)).scenes,
        );
        if (!cancelled) {
          setProject(nextProject);
          setSpec(nextSpec);
          setScenes(nextScenes);
        }
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
      <h2>项目 / 规格</h2>
      {error ? <p className="error">{error}</p> : null}
      <div className="card">
        <p>标题：{textOf(project.title)}</p>
        <p>语言：{textOf(project.language)}</p>
        <p>项目状态：{textOf(project.status)}</p>
      </div>
      <h3>Story Spec</h3>
      <div className="card">
        <p>规格状态：{textOf(spec.status)}</p>
        <p>必须写：{JSON.stringify(spec.must_write ?? [])}</p>
        <p>不得写：{JSON.stringify(spec.must_not_write ?? [])}</p>
        <p className="muted">规格批准不是 Canon 批准。</p>
      </div>
      <h3>场景（一章三场）</h3>
      <table>
        <thead>
          <tr>
            <th>顺序</th>
            <th>地点</th>
            <th>卡状态</th>
            <th>可生成</th>
          </tr>
        </thead>
        <tbody>
          {scenes.map((scene) => (
            <tr key={textOf(scene.id)}>
              <td>{textOf(scene.story_order)}</td>
              <td>{textOf(scene.location)}</td>
              <td>{textOf(scene.status)}</td>
              <td>{scene.generatable ? "是" : "否"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
