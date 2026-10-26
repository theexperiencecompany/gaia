/**
 * Every page imports @/lib/analytics, so a static posthog-js import there puts
 * the whole SDK in every page's eager bundle. The SDK must arrive only through
 * instrumentation-client's idle-time import, handed over with connectPostHog.
 */
import { describe, expect, it, vi } from "vitest";

const { sdkLoads } = vi.hoisted(() => ({ sdkLoads: { count: 0 } }));

vi.mock("posthog-js", () => {
  sdkLoads.count += 1;
  return { default: { __loaded: false } };
});

describe("@/lib/analytics", () => {
  it("does not load the PostHog SDK when imported", async () => {
    const analytics = await import("@/lib/analytics");
    analytics.track("chat:tools_button_clicked", { is_open: true });

    expect(sdkLoads.count).toBe(0);
  });
});
