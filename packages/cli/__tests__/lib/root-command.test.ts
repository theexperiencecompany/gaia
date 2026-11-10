import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { runAsRoot } from "../../src/lib/root-command.js";

// Real child processes; a fake sudo on PATH runs its command as this user.
const FAKE_SUDO = '#!/bin/sh\n[ "$1" = "-n" ] && shift\nexec "$@"\n';

let dir: string;
let savedPath: string | undefined;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-root-"));
  fs.writeFileSync(path.join(dir, "sudo"), FAKE_SUDO, { mode: 0o755 });
  savedPath = process.env.PATH;
  process.env.PATH = `${dir}:${savedPath}`;
});

afterEach(() => {
  process.env.PATH = savedPath;
  fs.rmSync(dir, { recursive: true, force: true });
});

describe("runAsRoot", () => {
  it("writes the command's output to the log and hands each line to onLine", async () => {
    const log = path.join(dir, "out.log");
    const lines: string[] = [];

    await runAsRoot("sh", ["-c", "echo one; echo two >&2"], log, (line) =>
      lines.push(line),
    );

    const written = fs.readFileSync(log, "utf-8");
    expect(written).toContain("one");
    expect(written).toContain("two");
    expect(lines).toEqual(expect.arrayContaining(["one", "two"]));
  });

  it("names the log file when the command fails", async () => {
    const log = path.join(dir, "fail.log");

    await expect(
      runAsRoot("sh", ["-c", "echo broke; exit 3"], log),
    ).rejects.toThrow(`(exit 3). Its output is in ${log}`);
    expect(fs.readFileSync(log, "utf-8")).toContain("broke");
  });
});
