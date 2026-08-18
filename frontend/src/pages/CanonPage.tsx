import { useEffect, useState } from "react";
import { apiGet, asList, asRecord, textOf } from "../api";

export function CanonPage({ projectId }: { projectId: string }) {
  const [error, setError] = useState("");
  const [facts, setFacts] = useState<Record<string, unknown>[]>([]);
  const [snapshots, setSnapshots] = useState<Record<string, unknown>[]>([]);
  const [snapshotFacts, setSnapshotFacts] = useState<Record<string, unknown>[]>(
    [],
  );

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const nextFacts = asList(
          asRecord(await apiGet(`/projects/${projectId}/canon-facts`)).facts,
        );
        const nextSnapshots = asList(
          asRecord(await apiGet(`/projects/${projectId}/canon-snapshots`))
            .items,
        );
        let captured: Record<string, unknown>[] = [];
        const first = nextSnapshots[0];
        if (first) {
          captured = asList(
            asRecord(
              await apiGet(
                `/projects/${projectId}/canon-snapshots/${textOf(first.id)}/facts`,
              ),
            ).facts,
          );
        }
        if (!cancelled) {
          setFacts(nextFacts);
          setSnapshots(nextSnapshots);
          setSnapshotFacts(captured);
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
      <h2>Canon 事实与 Snapshot</h2>
      {error ? <p className="error">{error}</p> : null}
      <p className="muted">
        当前 Canon 与冻结快照分开。快照不代替 live Canon。
      </p>
      <h3>生效事实</h3>
      <table>
        <thead>
          <tr>
            <th>谓语</th>
            <th>值</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {facts.map((fact) => (
            <tr key={textOf(fact.id)}>
              <td>{textOf(fact.predicate)}</td>
              <td>{JSON.stringify(fact.value_json)}</td>
              <td>{textOf(fact.status)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Snapshot</h3>
      {snapshots.map((snapshot) => (
        <div key={textOf(snapshot.id)} className="card">
          <p>id：{textOf(snapshot.id)}</p>
          <p>状态：{textOf(snapshot.status)}</p>
          <p>故事时间：{textOf(snapshot.as_of_story_time)}</p>
        </div>
      ))}
      <h3>快照内事实</h3>
      <p>条数：{snapshotFacts.length}</p>
    </section>
  );
}
