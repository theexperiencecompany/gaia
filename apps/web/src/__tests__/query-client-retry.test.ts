import { describe, expect, it } from "vitest";

import { getQueryClient } from "@/lib/queryClient";

type RetryPredicate = (failureCount: number, error: Error) => boolean;

const axiosError = (status: number) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status },
  });

const shouldRetry = (): RetryPredicate => {
  const { retry } = getQueryClient().getDefaultOptions().queries ?? {};
  if (typeof retry !== "function")
    throw new Error("queries.retry must decide per error, not per count");
  return retry as RetryPredicate;
};

describe("query retry policy", () => {
  it("never retries a paywall response", () => {
    // A 402 is the server's settled answer. Retrying it re-runs the whole
    // gate — a fresh checkout session on the server, another paywall open on
    // the client — three times over for a single blocked screen.
    expect(shouldRetry()(0, axiosError(402))).toBe(false);
  });

  it("never retries any other client error either", () => {
    expect(shouldRetry()(0, axiosError(403))).toBe(false);
    expect(shouldRetry()(0, axiosError(404))).toBe(false);
  });

  it("still retries a server error and a network failure twice", () => {
    expect(shouldRetry()(0, axiosError(500))).toBe(true);
    expect(shouldRetry()(1, axiosError(500))).toBe(true);
    expect(shouldRetry()(2, axiosError(500))).toBe(false);
    expect(shouldRetry()(0, new Error("Network Error"))).toBe(true);
  });
});
