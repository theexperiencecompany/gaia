// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const track = vi.fn();
const { refresh } = vi.hoisted(() => ({ refresh: vi.fn() }));

vi.mock("@/lib/analytics", () => ({ track }));
// The retry path refreshes server components alongside reset().
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

const { default: RouteError } = await import("@/components/shared/RouteError");
const { isChunkLoadError } = await import("@/lib/chunkErrorRecovery");

// The exact shape Turbopack's runtime throws when a soft navigation after a
// deploy requires a module that no chunk loaded by the old document defines.
const MODULE_FACTORY_MESSAGE =
  "Module 318381 was instantiated because it was required from module 866706, but the module factory is not available.";

const reload = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("location", { ...window.location, reload });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function pressTryAgain(): void {
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
}

describe("isChunkLoadError", () => {
  it.each([
    MODULE_FACTORY_MESSAGE,
    "Module 42 was instantiated as a runtime entry of chunk static/chunks/a.js, but the module factory is not available.",
    "Loading CSS chunk 7 failed.\n(/_next/static/css/abc.css)",
    "Loading chunk 7 failed.",
    "Failed to load chunk /_next/static/chunks/abc.js from module 1",
  ])("classifies a stale-deploy failure: %s", (message) => {
    expect(isChunkLoadError(new Error(message))).toBe(true);
  });

  it("leaves an ordinary render error to the retryable UI", () => {
    expect(isChunkLoadError(new TypeError("x is undefined"))).toBe(false);
  });
});

describe("RouteError", () => {
  it("reloads once for a module-factory error instead of showing the stuck UI", () => {
    render(
      <RouteError error={new Error(MODULE_FACTORY_MESSAGE)} reset={vi.fn()} />,
    );

    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Something went wrong")).toBeNull();
    expect(track).toHaveBeenCalledWith(
      "api:chunk_recovered",
      expect.objectContaining({ recovery_action: "reload" }),
    );
    expect(track).not.toHaveBeenCalledWith(
      "error:route_error_shown",
      expect.anything(),
    );
  });

  it("reports the error name and chunk flag when a recovery reload already failed", () => {
    sessionStorage.setItem("gaia:chunk-recovery-at", String(Date.now()));

    render(
      <RouteError error={new Error(MODULE_FACTORY_MESSAGE)} reset={vi.fn()} />,
    );

    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByText("Something went wrong")).toBeTruthy();
    expect(track).toHaveBeenCalledWith("error:route_error_shown", {
      error_type: "app_router_error_boundary",
      error_digest: undefined,
      error_name: "Error",
      is_chunk_error: true,
    });
  });

  it("reports a non-chunk error with its name and no chunk flag", () => {
    render(<RouteError error={new TypeError("boom")} reset={vi.fn()} />);

    expect(track).toHaveBeenCalledWith("error:route_error_shown", {
      error_type: "app_router_error_boundary",
      error_digest: undefined,
      error_name: "TypeError",
      is_chunk_error: false,
    });
  });

  it("reloads on Try again once reset() has failed for the same error", () => {
    const reset = vi.fn();
    const first = render(
      <RouteError error={new TypeError("same failure")} reset={reset} />,
    );
    pressTryAgain();
    expect(reset).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
    first.unmount();

    // reset() re-rendered the segment, which threw the same error again.
    render(<RouteError error={new TypeError("same failure")} reset={reset} />);
    pressTryAgain();

    expect(reset).toHaveBeenCalledTimes(1);
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
