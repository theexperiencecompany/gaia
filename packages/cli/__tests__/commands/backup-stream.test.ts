import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { streamCommandToFile } from "../../src/commands/backup/flow.js";

const MIB = 1024 * 1024;
// Above execa's 100 MB default maxBuffer, the size a real Mongo dump passes.
const DUMP_MIB = 110;
const EMIT_DUMP = `const b = Buffer.alloc(${MIB}, 97); let i = 0;
(function w() { while (i < ${DUMP_MIB}) { i++; if (!process.stdout.write(b)) return process.stdout.once("drain", w); } })();`;

describe("a database dump streams to disk", () => {
  it("writes a dump larger than any in-memory buffer, owner-only", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-dump-"));
    const file = path.join(dir, "mongo.gz");

    await streamCommandToFile(process.execPath, ["-e", EMIT_DUMP], dir, file);

    expect(fs.statSync(file).size).toBe(DUMP_MIB * MIB);
    expect(fs.statSync(file).mode & 0o777).toBe(0o600);
  }, 60_000);

  it("a failed dump leaves no file behind", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-dump-"));
    const file = path.join(dir, "mongo.gz");

    await expect(
      streamCommandToFile(
        process.execPath,
        ["-e", "process.stdout.write('partial'); process.exit(3)"],
        dir,
        file,
      ),
    ).rejects.toThrow();
    expect(fs.existsSync(file)).toBe(false);
  });
});
