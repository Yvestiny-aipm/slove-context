import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  fakeDraftJobsPath,
  fakeExtractJobsPath,
  shuttleDraftPromptPath,
  shuttleDraftsPath,
  shuttleExtractPromptPath,
  shuttleExtractsPath,
} from "../api";
import { ScenePage } from "./ScenePage";

function jsonResponse(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const SCENE = {
  id: "scene-1",
  story_order: 1,
  location: "河滩",
  status: "approved",
  generatable: true,
  goal: "拾得残玉",
  forbidden: ["禁止写出残玉来历"],
};

const DRAFT = {
  id: "draft-1",
  revision: 1,
  status: "Generated",
  body: "河滩风冷，林晚看见一点光，伸手拾起残玉。",
  input_versions: { snapshot_id: "snap-1" },
};

describe("scene shuttle buttons hit shuttle paths, not Fake jobs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("the four shuttle controls use shuttle routes only", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/scenes")) {
        return jsonResponse({ scenes: [SCENE] });
      }
      if (url.includes("/plans/current")) {
        return jsonResponse({
          snapshot_id: "snap-1",
          plan: { id: "plan-1" },
        });
      }
      if (url.includes("/drafts") && !url.includes("/shuttle")) {
        return jsonResponse({ items: [DRAFT] });
      }
      if (url.includes("/candidate-changes")) {
        return jsonResponse({ items: [] });
      }
      if (url.includes(shuttleDraftPromptPath("proj-1", "scene-1"))) {
        return jsonResponse({
          prompt: "目标：拾得残玉\n禁止：禁止写出残玉来历\n知识边界：无",
          purpose: "scene_draft",
          scene_id: "scene-1",
          is_canon: false,
        });
      }
      if (url.includes(shuttleExtractPromptPath("proj-1", "scene-1", "draft-1"))) {
        return jsonResponse({
          prompt: "只输出 JSON 数组",
          purpose: "extract",
          draft_id: "draft-1",
          is_canon: false,
        });
      }
      if (url.includes(shuttleDraftsPath("proj-1", "scene-1"))) {
        return jsonResponse({
          draft: { ...DRAFT, generation_model: "external-subscribed" },
          writes_canon: false,
        });
      }
      if (url.includes(shuttleExtractsPath("proj-1", "scene-1", "draft-1"))) {
        return jsonResponse({
          items: [{ id: "cand-1", status: "Extracted" }],
          writes_canon: false,
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ScenePage projectId="proj-1" />);

    await screen.findByRole("button", { name: "复制写稿提示词" });
    await user.click(screen.getByRole("button", { name: "复制写稿提示词" }));
    expect(await screen.findByText("已复制写稿提示词")).toBeInTheDocument();

    const draftBox = screen.getByPlaceholderText("把外部模型返回的正文贴在这里");
    await user.type(draftBox, "河滩风冷，林晚看见一点光，伸手拾起残玉。她把玉握在掌心。");
    await user.click(screen.getByRole("button", { name: "贴回正文" }));
    expect(
      await screen.findByText("已贴回正文（未批准，未写 Canon）"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "复制抽取提示词" }));
    expect(await screen.findByText("已复制抽取提示词")).toBeInTheDocument();

    const extractBox = screen.getByPlaceholderText("贴回抽取（JSON 数组）");
    await user.clear(extractBox);
    await user.type(
      extractBox,
      '[{{"subject":"林晚","predicate":"持有","object":"残玉"}}]',
    );
    await user.click(screen.getByRole("button", { name: "贴回抽取（JSON 数组）" }));
    expect(
      await screen.findByText("已贴回抽取（Extracted，未批准，未写 Canon）"),
    ).toBeInTheDocument();

    const urls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(
      urls.some((url) => url.includes(shuttleDraftPromptPath("proj-1", "scene-1"))),
    ).toBe(true);
    expect(
      urls.some((url) => url.includes(shuttleDraftsPath("proj-1", "scene-1"))),
    ).toBe(true);
    expect(
      urls.some((url) =>
        url.includes(shuttleExtractPromptPath("proj-1", "scene-1", "draft-1")),
      ),
    ).toBe(true);
    expect(
      urls.some((url) =>
        url.includes(shuttleExtractsPath("proj-1", "scene-1", "draft-1")),
      ),
    ).toBe(true);
    expect(
      urls.some((url) => url.includes(fakeDraftJobsPath("proj-1", "scene-1"))),
    ).toBe(false);
    expect(
      urls.some((url) =>
        url.includes(fakeExtractJobsPath("proj-1", "scene-1", "draft-1")),
      ),
    ).toBe(false);

    const mutating = fetchMock.mock.calls.filter(([, init]) => {
      const method = init && "method" in init ? String(init.method) : "GET";
      return method === "POST";
    });
    expect(
      mutating.every(([input]) => {
        const url = String(input);
        return url.includes("/shuttle/");
      }),
    ).toBe(true);
  });
});
