import { useEffect, useState } from "react";
import { apiGet, asList, asRecord, textOf } from "../api";

export function DagPage({ projectId }: { projectId: string }) {
  const [error, setError] = useState("");
  const [dags, setDags] = useState<Record<string, unknown>[]>([]);
  const [graph, setGraph] = useState<Record<string, unknown>>({});

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const scenes = asList(
          asRecord(await apiGet(`/projects/${projectId}/scenes`)).scenes,
        );
        const collected: Record<string, unknown>[] = [];
        for (const scene of scenes) {
          const listed = asList(
            asRecord(
              await apiGet(
                `/projects/${projectId}/scenes/${textOf(scene.id)}/dags`,
              ),
            ).items,
          );
          collected.push(...listed);
        }
        let nextGraph: Record<string, unknown> = {};
        if (collected[0]) {
          nextGraph = asRecord(
            await apiGet(
              `/projects/${projectId}/dags/${textOf(collected[0].id)}/graph`,
            ),
          );
        }
        if (!cancelled) {
          setDags(collected);
          setGraph(nextGraph);
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

  const nodes = asList(graph.nodes);

  return (
    <section>
      <h2>单场景 DAG</h2>
      {error ? <p className="error">{error}</p> : null}
      <p className="muted">
        canon_commit 仅在人类批准后走既有 4.2 submit。Worker 不批准。
      </p>
      {dags.map((dag) => (
        <div key={textOf(dag.id)} className="card">
          <p>DAG：{textOf(dag.id)}</p>
          <p>场景：{textOf(dag.scene_id)}</p>
          <p>状态：{textOf(dag.status)}</p>
        </div>
      ))}
      <h3>节点</h3>
      <table>
        <thead>
          <tr>
            <th>节点</th>
            <th>状态</th>
            <th>duration_ms</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((node) => (
            <tr key={textOf(node.node_id ?? node.id)}>
              <td>{textOf(node.node_id ?? node.id)}</td>
              <td>{textOf(node.status)}</td>
              <td>{textOf(node.duration_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
