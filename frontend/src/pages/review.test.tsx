import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  candidateApprovePath,
  candidateSubmitPath,
  reviewApprovePath,
} from "../api";
import { ReviewPage } from "./ReviewPage";

function jsonResponse(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const QUEUE = {
  items: [
    {
      id: "rq-1",
      subject_type: "candidate_change",
      subject_id: "cand-1",
      status: "Opened",
    },
  ],
};

describe("review buttons hit the correct API paths", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("approve hits 7.3 review-queue approve and does not submit", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/review-queue/rq-1/approve")) {
        return jsonResponse({
          item: QUEUE.items[0],
          auto_submitted: false,
          writes_canon: false,
        });
      }
      if (url.includes("/review-queue")) {
        return jsonResponse(QUEUE);
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ReviewPage projectId="proj-1" />);
    await screen.findByRole("button", { name: "批准" });
    await user.click(screen.getByRole("button", { name: "批准" }));
    const urls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(
      urls.some((url) =>
        url.includes(reviewApprovePath("proj-1", "rq-1")),
      ),
    ).toBe(true);
    expect(
      urls.some((url) => url.includes(candidateSubmitPath("proj-1", "cand-1"))),
    ).toBe(false);
    expect(
      urls.some((url) =>
        url.includes(candidateApprovePath("proj-1", "cand-1")),
      ),
    ).toBe(false);
    expect(await screen.findByText("已批准（未提交 Canon）")).toBeInTheDocument();
    const approveCall = fetchMock.mock.calls.find(([input]) =>
      String(input).includes("/review-queue/rq-1/approve"),
    );
    expect(approveCall?.[1]?.method).toBe("POST");
  });

  it("submit is a distinct click that hits only the 4.2 submit path", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/candidate-changes/cand-1/submit")) {
        return jsonResponse({ writes_canon: true, auto_submitted: false });
      }
      if (url.includes("/review-queue")) {
        return jsonResponse(QUEUE);
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ReviewPage projectId="proj-1" />);
    await screen.findByRole("button", { name: "提交 Canon" });
    await user.click(screen.getByRole("button", { name: "提交 Canon" }));
    const mutating = fetchMock.mock.calls.filter(([, init]) => {
      const method = init && "method" in init ? String(init.method) : "GET";
      return method === "POST";
    });
    expect(mutating).toHaveLength(1);
    expect(String(mutating[0][0])).toContain(
      candidateSubmitPath("proj-1", "cand-1"),
    );
    expect(String(mutating[0][0])).not.toContain("/approve");
    expect(
      await screen.findByText("已提交 Canon（单独动作）"),
    ).toBeInTheDocument();
  });
});
