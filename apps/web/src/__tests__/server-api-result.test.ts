/** A server read's 404 is an answer only where the caller asked for one; every other failure throws. */
import { ApiError } from "@shared/api";
import { describe, expect, it } from "vitest";

import { serverData, serverDataOrNull } from "@/lib/api/server";

const response = (status: number) => new Response(null, { status });

describe("server API results", () => {
  it("returns the data of a successful read", () => {
    expect(serverData({ data: { ok: true }, response: response(200) })).toEqual(
      { ok: true },
    );
  });

  it("throws an ApiError carrying the status for a failed read", () => {
    expect(() =>
      serverData({ error: { message: "boom" }, response: response(500) }),
    ).toThrow(ApiError);
  });

  it("answers null for a 404 only through serverDataOrNull", () => {
    const notFound = { error: { message: "nope" }, response: response(404) };
    expect(serverDataOrNull(notFound)).toBeNull();
    expect(() => serverData(notFound)).toThrow(ApiError);
    expect(() =>
      serverDataOrNull({ error: {}, response: response(502) }),
    ).toThrow(ApiError);
  });
});
