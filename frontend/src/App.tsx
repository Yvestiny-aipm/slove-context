import { useEffect, useState } from "react";
import { apiGet, asList, asRecord, textOf } from "./api";
import { Layout } from "./components/Layout";
import { CanonPage } from "./pages/CanonPage";
import { DagPage } from "./pages/DagPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ReleasePage } from "./pages/ReleasePage";
import { ReviewPage } from "./pages/ReviewPage";
import { ScenePage } from "./pages/ScenePage";
import { ValidationPage } from "./pages/ValidationPage";

function currentPage(): string {
  const hash = window.location.hash.replace(/^#\/?/, "");
  return hash || "overview";
}

export function App() {
  const [page, setPage] = useState(currentPage);
  const [projectId, setProjectId] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const onHash = () => setPage(currentPage());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    apiGet("/projects")
      .then((body) => {
        const items = asList(asRecord(body).items);
        if (!items[0]) {
          setError("尚未播种。请先运行 python -m slove_context.demo");
          return;
        }
        setProjectId(textOf(items[0].id));
      })
      .catch((err: unknown) => setError(String(err)));
  }, []);

  let content = <p>加载中…</p>;
  if (error) {
    content = <p className="error">{error}</p>;
  } else if (projectId) {
    if (page === "project") content = <ProjectPage projectId={projectId} />;
    else if (page === "canon") content = <CanonPage projectId={projectId} />;
    else if (page === "scene") content = <ScenePage projectId={projectId} />;
    else if (page === "validation")
      content = <ValidationPage projectId={projectId} />;
    else if (page === "review") content = <ReviewPage projectId={projectId} />;
    else if (page === "dag") content = <DagPage projectId={projectId} />;
    else if (page === "release") content = <ReleasePage projectId={projectId} />;
    else content = <OverviewPage projectId={projectId} />;
  }

  return <Layout page={page}>{content}</Layout>;
}
