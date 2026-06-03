import { describe, it, expect } from "vitest";
import { isBackofficePath } from "./route";

describe("isBackofficePath", () => {
  it("matches the backoffice root and subpaths", () => {
    expect(isBackofficePath("/backoffice")).toBe(true);
    expect(isBackofficePath("/backoffice/")).toBe(true);
    expect(isBackofficePath("/backoffice/tasks/5")).toBe(true);
  });

  it("does not match the customer app", () => {
    expect(isBackofficePath("/")).toBe(false);
    expect(isBackofficePath("/chat")).toBe(false);
    expect(isBackofficePath("/backofficex")).toBe(false);
  });
});
