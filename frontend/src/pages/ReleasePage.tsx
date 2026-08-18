import { useEffect, useState } from "react";
import { apiGet, asList, asRecord, textOf } from "../api";

export function ReleasePage({ projectId }: { projectId: string }) {
  const [error, setError] = useState("");
  const [checks, setChecks] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    let cancelled = false;
    apiGet(`/projects/${projectId}/release-checks`)
      .then((body) => {
        if (!cancelled) setChecks(asList(asRecord(body).items));
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return (
    <section>
      <h2>发布门</h2>
      {error ? <p className="error">{error}</p> : null}
      <p className="muted">
        八项只读预发布检查。失败时展示机器可读失败列表。不写 Canon。
      </p>
      {checks.map((check) => {
        const gates = asList(check.gates);
        const failures = asList(check.failures);
        return (
          <div key={textOf(check.id)} className="card">
            <p>检查：{textOf(check.id)}</p>
            <p>总结果：{check.passed ? "通过" : "未通过"} / {textOf(check.status)}</p>
            <table>
              <thead>
                <tr>
                  <th>门</th>
                  <th>通过</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {gates.map((gate) => (
                  <tr
                    key={textOf(gate.gate_id ?? gate.id)}
                    className={gate.passed ? "gate-pass" : "gate-fail"}
                  >
                    <td>{textOf(gate.gate_id ?? gate.id)}</td>
                    <td>{gate.passed ? "是" : "否"}</td>
                    <td>{textOf(gate.message ?? gate.detail)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!check.passed ? (
              <>
                <h3>机器可读失败列表</h3>
                <pre>{JSON.stringify(failures, null, 2)}</pre>
              </>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}
