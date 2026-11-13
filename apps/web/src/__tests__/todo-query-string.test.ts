import { buildQueryString } from "@shared/api/queryBuilder";
import { describe, expect, it } from "vitest";

describe("buildQueryString", () => {
  it("serializes string arrays as repeated keys for FastAPI list params", () => {
    const qs = buildQueryString({
      labels: ["work", "urgent"],
      completed: false,
    });
    const params = new URLSearchParams(qs.slice(1));
    expect(params.getAll("labels")).toEqual(["work", "urgent"]);
    expect(params.get("completed")).toBe("false");
  });

  it("handles a single label without comma-joining artifacts", () => {
    const qs = buildQueryString({ labels: ["my label"] });
    expect(new URLSearchParams(qs.slice(1)).getAll("labels")).toEqual([
      "my label",
    ]);
  });

  it("skips empty arrays and nullish values", () => {
    expect(buildQueryString({ labels: [] })).toBe("");
    expect(
      buildQueryString({ q: undefined, project_id: null, search: "" }),
    ).toBe("");
  });

  it("keeps the skip/limit to page/per_page mapping", () => {
    const params = new URLSearchParams(
      buildQueryString({ skip: 50, limit: 25 }).slice(1),
    );
    expect(params.get("page")).toBe("3");
    expect(params.get("per_page")).toBe("25");
  });
});
