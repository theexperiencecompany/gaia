// @vitest-environment jsdom
/** A caught render error still reaches Sentry, now through its lazily loaded client rather than a first-load import. */
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ErrorBoundary from "@/components/shared/ErrorBoundary";

const captureException = vi.fn();

vi.mock("@/lib/observability/sentryClient", () => ({
  captureException: (...args: unknown[]) => captureException(...args),
}));
vi.mock("@/lib/analytics", () => ({ track: () => undefined }));

function Throws(): never {
  throw new Error("render failed");
}

describe("ErrorBoundary", () => {
  it("reports the caught error to Sentry with its scope tag and component stack", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <ErrorBoundary scope="todo-row" fallback={null}>
        <Throws />
      </ErrorBoundary>,
    );

    await waitFor(() => expect(captureException).toHaveBeenCalledTimes(1));
    const [error, context] = captureException.mock.calls[0];
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("render failed");
    expect(context).toMatchObject({
      tags: { error_boundary: "todo-row" },
      extra: { componentStack: expect.stringContaining("Throws") },
    });
  });
});
