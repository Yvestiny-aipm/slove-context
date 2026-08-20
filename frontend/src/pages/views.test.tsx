import { render, screen } from "@testing-library/react";
import { Banner, DEMO_BANNER } from "../components/Banner";
import { Layout } from "../components/Layout";
import { OverviewPage } from "./OverviewPage";
import { ProjectPage } from "./ProjectPage";
import { ReleasePage } from "./ReleasePage";
import { ReviewPage } from "./ReviewPage";

function jsonResponse(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("key views render", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the Demo banner on the layout", () => {
    render(
      <Layout page="overview">
        <p>内容</p>
      </Layout>,
    );
    expect(screen.getByRole("status")).toHaveTextContent(DEMO_BANNER);
    expect(screen.getByText("总览")).toBeInTheDocument();
    expect(screen.getByText("审校")).toBeInTheDocument();
    expect(screen.getByText("发布门")).toBeInTheDocument();
  });

  it("renders overview loop labels after mock fetch", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/specs/current")) {
          return jsonResponse({ status: "Effective" });
        }
        if (url.endsWith("/scenes")) {
          return jsonResponse({
            scenes: [
              {
                id: "scene-1",
                story_order: 1,
                location: "河滩",
                status: "approved",
              },
            ],
          });
        }
        if (url.includes("/canon-snapshots")) {
          return jsonResponse({ items: [{ id: "snap-1", status: "frozen" }] });
        }
        if (url.includes("/drafts")) {
          return jsonResponse({
            items: [{ id: "draft-1", body: "FAKE_SCENE_DRAFT_PROSE" }],
          });
        }
        if (url.includes("/candidate-changes")) {
          return jsonResponse({
            items: [{ id: "cand-1", status: "AwaitingVerdict" }],
          });
        }
        return jsonResponse({});
      }),
    );
    render(<OverviewPage projectId="proj-1" />);
    expect(await screen.findByText("总览")).toBeInTheDocument();
    expect(await screen.findByText("当前卡在：人审")).toBeInTheDocument();
    expect(screen.getByText("规格")).toBeInTheDocument();
    expect(screen.getByText("写 Canon")).toBeInTheDocument();
  });

  it("renders project and release headings", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/projects/proj-1")) {
          return jsonResponse({
            title: "青石夜祠（Demo）",
            language: "zh-CN",
            status: "Active",
          });
        }
        if (url.endsWith("/specs/current")) {
          return jsonResponse({
            status: "Effective",
            must_write: ["只写林晚在青石镇的七日"],
            must_not_write: ["禁止第二主角视角"],
          });
        }
        if (url.endsWith("/scenes")) {
          return jsonResponse({ scenes: [] });
        }
        if (url.includes("/release-checks")) {
          return jsonResponse({
            items: [
              {
                id: "check-1",
                passed: false,
                status: "failed",
                gates: [
                  { gate_id: "drafts_human_approved", passed: false },
                  { gate_id: "snapshot_frozen", passed: true },
                ],
                failures: [{ gate_id: "drafts_human_approved" }],
              },
            ],
          });
        }
        return jsonResponse({});
      }),
    );
    render(<ProjectPage projectId="proj-1" />);
    expect(await screen.findByText("项目 / 规格")).toBeInTheDocument();
    render(<ReleasePage projectId="proj-1" />);
    expect(await screen.findByText("发布门")).toBeInTheDocument();
    expect(await screen.findByText("机器可读失败列表")).toBeInTheDocument();
  });

  it("renders review controls", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        jsonResponse({
          items: [
            {
              id: "rq-1",
              subject_type: "candidate_change",
              subject_id: "cand-1",
              status: "Opened",
            },
          ],
        }),
      ),
    );
    render(<ReviewPage projectId="proj-1" />);
    expect(await screen.findByText("审校队列")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "批准" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "拒绝" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交 Canon" })).toBeInTheDocument();
    expect(screen.getByText(/不自动 submit/)).toBeInTheDocument();
  });

  it("renders the isolated banner text", () => {
    render(<Banner />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Demo / Fake Provider / DeepSeek 可配置 / 非自动批准",
    );
  });
});
