import { afterEach, describe, expect, it, vi } from "vitest";

import { currentConversationId } from "./currentConversationId";

function at(pathname: string) {
  // The helper only reads window.location.pathname; a stub keeps this a pure
  // parser test, with no router or jsdom needed (vitest runs in node here).
  vi.stubGlobal("window", { location: { pathname } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("currentConversationId", () => {
  it("reads the id from a chat path", () => {
    at("/c/6ac45bb5-c7fc-4797-901c-1f423eb105d4");
    expect(currentConversationId()).toBe(
      "6ac45bb5-c7fc-4797-901c-1f423eb105d4",
    );
  });

  it("reads it through a locale prefix", () => {
    at("/en/c/conv-1");
    expect(currentConversationId()).toBe("conv-1");
  });

  it("returns undefined for a new chat", () => {
    at("/");
    expect(currentConversationId()).toBeUndefined();
  });

  it("returns undefined when there is no browser window", () => {
    vi.unstubAllGlobals();
    expect(currentConversationId()).toBeUndefined();
  });

  it("stops at a query string or fragment", () => {
    at("/c/conv-1?foo=bar");
    expect(currentConversationId()).toBe("conv-1");
  });
});
