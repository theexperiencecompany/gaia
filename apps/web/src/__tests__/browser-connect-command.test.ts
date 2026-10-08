/**
 * The import-logins modal hands the user one command to paste, in whichever
 * runner they prefer. These pin the pieces that must be exactly right for it
 * to work against any deployment: the bare origin the tool is pointed at, when
 * that override is (and isn't) spelled out, each runner's command shape, that
 * the from-source runner is only offered against a developer's localhost API,
 * and the countdown that tells the user the code is still live.
 */
import { describe, expect, it } from "vitest";
import {
  buildConnectCommand,
  connectApiOrigin,
  connectApiOverride,
  connectRunnersFor,
  formatCountdown,
  isLocalApiOrigin,
} from "@/features/browser/utils";

describe("connectApiOrigin", () => {
  it("strips the /api/v1 path so the tool gets a bare origin", () => {
    expect(connectApiOrigin("http://localhost:8510/api/v1/")).toBe(
      "http://localhost:8510",
    );
    expect(connectApiOrigin("https://api.example.com/api/v1")).toBe(
      "https://api.example.com",
    );
  });
});

describe("connectApiOverride", () => {
  it("is null on production, where the tool's default already matches", () => {
    expect(connectApiOverride("https://api.heygaia.io/api/v1/")).toBeNull();
  });

  it("names the origin for dev and self-hosted APIs", () => {
    expect(connectApiOverride("http://localhost:8510/api/v1/")).toBe(
      "http://localhost:8510",
    );
  });
});

describe("isLocalApiOrigin", () => {
  it("recognises loopback origins", () => {
    expect(isLocalApiOrigin("http://localhost:8510")).toBe(true);
    expect(isLocalApiOrigin("http://127.0.0.1:8000")).toBe(true);
    expect(isLocalApiOrigin("http://[::1]:8000")).toBe(true);
  });

  it("treats any other host as a real deployment", () => {
    expect(isLocalApiOrigin("https://api.heygaia.io")).toBe(false);
    expect(isLocalApiOrigin("https://gaia.internal.example")).toBe(false);
  });
});

describe("connectRunnersFor", () => {
  it("leads with curl and never offers source against a real deployment", () => {
    expect(connectRunnersFor(null)).toEqual(["curl", "npx", "pnpm", "bun"]);
    expect(connectRunnersFor("https://gaia.internal.example")).toEqual([
      "curl",
      "npx",
      "pnpm",
      "bun",
    ]);
  });

  it("adds source against a localhost API", () => {
    expect(connectRunnersFor("http://localhost:8510")).toEqual([
      "curl",
      "npx",
      "pnpm",
      "bun",
      "source",
    ]);
  });
});

describe("buildConnectCommand", () => {
  const token = "abc123";

  it("curl pipes the installer to sh and passes the flags after --", () => {
    expect(
      buildConnectCommand({ token, apiOrigin: null, runner: "curl" }),
    ).toBe(
      "curl -fsSL https://heygaia.io/connect.sh | sh -s -- --token abc123",
    );
  });

  it("the npm runners share one shape", () => {
    expect(buildConnectCommand({ token, apiOrigin: null, runner: "npx" })).toBe(
      "npx @heygaia/cli connect --token abc123",
    );
    expect(
      buildConnectCommand({ token, apiOrigin: null, runner: "pnpm" }),
    ).toBe("pnpm dlx @heygaia/cli connect --token abc123");
    expect(buildConnectCommand({ token, apiOrigin: null, runner: "bun" })).toBe(
      "bunx @heygaia/cli connect --token abc123",
    );
  });

  it("appends --api for a self-hosted deployment on every runner", () => {
    const apiOrigin = "https://gaia.internal.example";
    expect(buildConnectCommand({ token, apiOrigin, runner: "curl" })).toBe(
      "curl -fsSL https://heygaia.io/connect.sh | sh -s -- --token abc123 --api https://gaia.internal.example",
    );
    expect(buildConnectCommand({ token, apiOrigin, runner: "npx" })).toBe(
      "npx @heygaia/cli connect --token abc123 --api https://gaia.internal.example",
    );
  });

  it("source runs the Go module from the repo root against the local API", () => {
    expect(
      buildConnectCommand({
        token,
        apiOrigin: "http://localhost:8510",
        runner: "source",
      }),
    ).toBe(
      "go run -C tools/gaia-connect . --token abc123 --api http://localhost:8510",
    );
  });

  it("source refuses to run without an explicit API origin", () => {
    expect(() =>
      buildConnectCommand({ token, apiOrigin: null, runner: "source" }),
    ).toThrow(/explicit API origin/);
  });
});

describe("formatCountdown", () => {
  it("renders m:ss with a padded seconds field", () => {
    expect(formatCountdown(598)).toBe("9:58");
    expect(formatCountdown(65)).toBe("1:05");
  });

  it("never goes negative once the code has expired", () => {
    expect(formatCountdown(0)).toBe("0:00");
    expect(formatCountdown(-30)).toBe("0:00");
  });
});
