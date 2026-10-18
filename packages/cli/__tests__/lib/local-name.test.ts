import { describe, expect, it } from "vitest";
import {
  LOCAL_NAME_URL,
  localNameAction,
  localNameBlocker,
} from "../../src/lib/local-name.js";

describe("localNameAction", () => {
  it("sets the name up by default", () => {
    expect(
      localNameAction({
        optedOut: false,
        domain: undefined,
        setUpBefore: false,
      }),
    ).toBe("set-up");
  });

  it("re-checks a name an earlier run set up", () => {
    expect(
      localNameAction({
        optedOut: false,
        domain: undefined,
        setUpBefore: true,
      }),
    ).toBe("set-up");
  });

  it("leaves the name alone when a domain is served, since Caddy then needs port 80", () => {
    expect(
      localNameAction({
        optedOut: false,
        domain: "gaia.example.com",
        setUpBefore: false,
      }),
    ).toBe("none");
  });

  it("removes an earlier name once a domain takes port 80", () => {
    expect(
      localNameAction({
        optedOut: false,
        domain: "gaia.example.com",
        setUpBefore: true,
      }),
    ).toBe("remove");
  });

  it("removes an earlier name on --no-local-name", () => {
    expect(
      localNameAction({ optedOut: true, domain: undefined, setUpBefore: true }),
    ).toBe("remove");
  });

  it("does nothing on --no-local-name when no name was ever set up", () => {
    expect(
      localNameAction({
        optedOut: true,
        domain: undefined,
        setUpBefore: false,
      }),
    ).toBe("none");
  });
});

describe("localNameBlocker", () => {
  it("allows Node 24 and newer on Linux and macOS", () => {
    expect(localNameBlocker("v24.0.0", "linux")).toBeNull();
    expect(localNameBlocker("v26.1.0", "darwin")).toBeNull();
  });

  it("names the Node version portless needs on an older Node", () => {
    expect(localNameBlocker("v22.11.0", "linux")).toBe(
      "it needs Node.js 24 or newer, and this is Node.js 22.11.0",
    );
  });

  it("refuses platforms without an mDNS publisher it drives", () => {
    expect(localNameBlocker("v24.0.0", "win32")).toBe(
      "it works only on Linux and macOS",
    );
  });
});

describe("LOCAL_NAME_URL", () => {
  it("is plain HTTP, so other devices never meet an untrusted certificate", () => {
    expect(LOCAL_NAME_URL).toBe("http://gaia.local");
  });
});
