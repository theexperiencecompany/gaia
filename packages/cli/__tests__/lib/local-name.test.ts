import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { recordedLocalName } from "../../src/lib/config.js";
import { localNameUrl } from "../../src/lib/endpoints.js";
import {
  localNameAction,
  localNameBlocker,
  localNameCandidates,
  localNameHolder,
} from "../../src/lib/local-name.js";
import { existingLogNote } from "../../src/lib/logs.js";

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
    expect(localNameBlocker("v24.0.0", "linux", 3000)).toBeNull();
    expect(localNameBlocker("v26.1.0", "darwin", 3000)).toBeNull();
  });

  it("names the Node version portless needs on an older Node", () => {
    expect(localNameBlocker("v22.11.0", "linux", 3000)).toBe(
      "it needs Node.js 24 or newer, and this is Node.js 22.11.0",
    );
  });

  it("names GAIA itself on port 80 (a domain's port, left behind) as the cause, not mDNS", () => {
    expect(localNameBlocker("v24.0.0", "linux", 80)).toBe(
      "GAIA itself uses port 80, which the name's proxy needs; run 'gaia up --web-port 3000' to move GAIA off it",
    );
  });

  it("refuses platforms without an mDNS publisher it drives", () => {
    expect(localNameBlocker("v24.0.0", "win32", 3000)).toBe(
      "it works only on Linux and macOS",
    );
  });
});

describe("localNameUrl", () => {
  it("is plain HTTP, so other devices never meet an untrusted certificate", () => {
    expect(localNameUrl("gaia")).toBe("http://gaia.local");
    expect(localNameUrl("gaia-2")).toBe("http://gaia-2.local");
  });
});

describe("localNameCandidates", () => {
  it("tries gaia, then the next free mDNS name, as a second GAIA on the network must", () => {
    expect(localNameCandidates(null).slice(0, 3)).toEqual([
      "gaia",
      "gaia-2",
      "gaia-3",
    ]);
  });

  it("keeps the name an earlier run recorded first, so a rerun doesn't move it", () => {
    const candidates = localNameCandidates("gaia-2");
    expect(candidates[0]).toBe("gaia-2");
    expect(candidates.filter((name) => name === "gaia-2")).toHaveLength(1);
    expect(candidates).toContain("gaia");
  });
});

describe("recordedLocalName", () => {
  it("reads a name only once a run confirmed it resolves here; true marks an attempt", () => {
    expect(recordedLocalName("gaia-3")).toBe("gaia-3");
    expect(recordedLocalName(true)).toBeNull();
    expect(recordedLocalName(undefined)).toBeNull();
  });
});

describe("localNameHolder", () => {
  const own = ["192.168.139.10", "fd07:b51a:cc66:0:4da:a9ff:fea6:a62b"];

  it("is this computer when the name resolves to one of its addresses", () => {
    expect(localNameHolder("192.168.139.10", own)).toBe("this-computer");
    expect(localNameHolder("fd07:b51a:cc66:0:4da:a9ff:fea6:a62b", own)).toBe(
      "this-computer",
    );
  });

  it("is another computer when a second GAIA on the network answers for the name", () => {
    expect(localNameHolder("192.168.139.14", own)).toBe("another-computer");
  });

  it("is nobody when the name does not resolve", () => {
    expect(localNameHolder(null, own)).toBe("nobody");
  });
});

describe("existingLogNote", () => {
  it("names a log only once something was written to it", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "gaia-log-note-"));
    const logPath = path.join(dir, "local-name.log");
    try {
      expect(existingLogNote(logPath)).toBe("");
      writeFileSync(logPath, "");
      expect(existingLogNote(logPath)).toBe("");
      writeFileSync(logPath, "avahi said no\n");
      expect(existingLogNote(logPath)).toBe(` (log: ${logPath})`);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
