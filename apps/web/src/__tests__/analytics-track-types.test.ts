/**
 * `track` compiles only for web-owned catalog events with their exact props.
 * The `@ts-expect-error` lines are the test: `pnpm type` fails if any of them
 * starts compiling, i.e. if a raw string or a foreign event gets through.
 */
import { describe, expect, it, vi } from "vitest";

import { track } from "@/lib/analytics";

vi.mock("posthog-js", () => ({ default: { __loaded: false } }));

describe("track", () => {
  it("accepts a web event with its catalog props", () => {
    expect(() =>
      track("chat:tools_button_clicked", { is_open: true }),
    ).not.toThrow();
  });

  it("rejects names and props outside the web catalog at compile time", () => {
    // @ts-expect-error a raw string is not a WebEventName
    const raw = () => track("not:an_event", {});
    const server = () =>
      // @ts-expect-error chat:message_submitted is server-owned
      track("chat:message_submitted", { source: "web", has_files: false });
    // @ts-expect-error a property the catalog does not define
    const extra = () => track("ui:sidebar_collapsed", { text: "hello" });
    // @ts-expect-error a required property is missing
    const missing = () => track("chat:tools_button_clicked", {});
    const rejected = [raw, server, extra, missing];
    expect(rejected).toHaveLength(4);
  });
});
