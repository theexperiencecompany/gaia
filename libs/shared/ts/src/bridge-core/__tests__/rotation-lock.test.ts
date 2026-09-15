// Mutual exclusion for refresh-token rotation across processes sharing one
// state dir: two holders must never exchange the same token concurrently.

import { randomUUID } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

async function freshModules() {
  vi.resetModules();
  const env = await import("../env.js");
  const lock = await import("../rotation-lock.js");
  return { ...env, ...lock };
}

describe("rotation lock", () => {
  let stateDir: string;

  beforeEach(() => {
    stateDir = join(tmpdir(), `gaia-rotation-test-${randomUUID()}`);
  });

  afterEach(() => {
    vi.resetModules();
  });

  it("serializes concurrent rotations in acquisition order", async () => {
    const { configureBridge, withRotationLock } = await freshModules();
    configureBridge({ stateDir });
    const order: string[] = [];
    let releaseFirst!: () => void;
    const gate = new Promise<void>((r) => {
      releaseFirst = r;
    });
    const first = withRotationLock(async () => {
      order.push("first-start");
      await gate;
      order.push("first-end");
    });
    // Let the first holder actually acquire before the second contends.
    await new Promise((r) => setTimeout(r, 50));
    const second = withRotationLock(async () => {
      order.push("second");
    });
    releaseFirst();
    await Promise.all([first, second]);
    expect(order).toEqual(["first-start", "first-end", "second"]);
  });

  it("releases the lock when the body throws", async () => {
    const { configureBridge, withRotationLock } = await freshModules();
    configureBridge({ stateDir });
    await expect(
      withRotationLock(async () => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
    expect(readdirSync(stateDir)).not.toContain("credentials.lock");
    // And the dir is acquirable again afterwards.
    await expect(withRotationLock(async () => "ok")).resolves.toBe("ok");
  });

  it("steals a lock whose holder died mid-rotation", async () => {
    const { configureBridge, withRotationLock } = await freshModules();
    configureBridge({ stateDir });
    const dir = join(stateDir, "credentials.lock");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "stamp"), String(Date.now() - 60_000));
    await expect(withRotationLock(async () => "stolen")).resolves.toBe(
      "stolen",
    );
    expect(existsSync(dir)).toBe(false);
  });

  it("waits on a live holder instead of stealing it", async () => {
    const { configureBridge, withRotationLock } = await freshModules();
    configureBridge({ stateDir });
    // Fresh stamp = live holder; prove we don't steal it by asserting a quick
    // contender is still waiting (never ran) rather than waiting out the full
    // 30s acquire timeout.
    const dir = join(stateDir, "credentials.lock");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "stamp"), String(Date.now()));
    let ran = false;
    const contender = withRotationLock(async () => {
      ran = true;
    });
    await new Promise((r) => setTimeout(r, 300));
    expect(ran).toBe(false);
    expect(existsSync(dir)).toBe(true);
    // Cleanup so the pending contender doesn't linger past the test.
    rmSync(dir, { recursive: true, force: true });
    await contender;
    expect(ran).toBe(true);
  });
});
