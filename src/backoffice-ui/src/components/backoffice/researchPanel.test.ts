import { describe, expect, it } from "vitest";
import { researchState, type ResearchView } from "./ResearchPanel";

const view: ResearchView = {
  taskId: 42,
  summary: "SUPPORTS APPROVING\n- 4 comparable cases approved",
  reviewer: "Backoffice Reviewer",
  createdAt: "2026-09-21T10:00:00Z",
  researchRunId: "r-1",
};

describe("researchState", () => {
  it("is idle before anything has been run", () => {
    expect(researchState(null, false)).toBe("idle");
  });

  it("is running while the agent is working", () => {
    expect(researchState(null, true)).toBe("running");
  });

  it("is ready once a summary exists", () => {
    // A stored summary renders on load; the reviewer never re-runs to read it.
    expect(researchState(view, false)).toBe("ready");
  });

  it("stays running when a re-run is in flight over an existing summary", () => {
    expect(researchState(view, true)).toBe("running");
  });
});
