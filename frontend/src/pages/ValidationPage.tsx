import { useEffect, useState } from "react";
import { apiGet, asList, asRecord, textOf } from "../api";

export function ValidationPage({ projectId }: { projectId: string }) {
  const [error, setError] = useState("");
  const [runs, setRuns] = useState<Record<string, unknown>[]>([]);
  const [reports, setReports] = useState<Record<string, unknown>[]>([]);
  const [repairs, setRepairs] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const nextRuns = asList(
          asRecord(await apiGet(`/projects/${projectId}/validation-runs`))
            .items,
        );
        const nextReports: Record<string, unknown>[] = [];
        for (const run of nextRuns) {
          try {
            nextReports.push(
              asRecord(
                await apiGet(
                  `/projects/${projectId}/validation-runs/${textOf(run.id)}/report`,
                ),
              ),
            );
          } catch {
            // Report may be missing on cancelled / exec-failed runs.
          }
        }
        const nextRepairs = asList(
          asRecord(await apiGet(`/projects/${projectId}/repair-tasks`)).items,
        );
        if (!cancelled) {
          setRuns(nextRuns);
          setReports(nextReports);
          setRepairs(nextRepairs);
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
      <h2>校验报告 / 返工</h2>
      {error ? <p className="error">{error}</p> : null}
      <p className="muted">
        Validation Run 通过只到 AwaitingVerdict，不是批准，不写 Canon。
      </p>
      <h3>Validation Runs</h3>
      <table>
        <thead>
          <tr>
            <th>id</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={textOf(run.id)}>
              <td>{textOf(run.id)}</td>
              <td>{textOf(run.status)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {reports.map((report) => (
        <div key={textOf(report.id)} className="card">
          <p>报告结局：{textOf(report.outcome ?? report.status)}</p>
          <pre>{JSON.stringify(report.violations ?? [], null, 2)}</pre>
        </div>
      ))}
      <h3>Repair Tasks</h3>
      {repairs.length === 0 ? (
        <p className="muted">当前没有返工任务（Demo 默认校验通过）。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>id</th>
              <th>状态</th>
              <th>动作</th>
            </tr>
          </thead>
          <tbody>
            {repairs.map((task) => (
              <tr key={textOf(task.id)}>
                <td>{textOf(task.id)}</td>
                <td>{textOf(task.status)}</td>
                <td>{textOf(task.action)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
