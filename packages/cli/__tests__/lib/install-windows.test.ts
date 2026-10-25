import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";

const INSTALLER = fileURLToPath(new URL("../../install.sh", import.meta.url));
const fakeBin = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-uname-"));

afterAll(() => fs.rmSync(fakeBin, { recursive: true, force: true }));

/** install.sh as Git Bash on Windows runs it: uname names MINGW. */
function runOnWindowsShell(): { status: number | null; output: string } {
  fs.writeFileSync(
    path.join(fakeBin, "uname"),
    "#!/bin/sh\necho MINGW64_NT-10.0-26100\n",
    { mode: 0o755 },
  );
  // Should the guard ever regress, nothing gets downloaded or installed on this machine.
  for (const tool of ["npm", "curl", "wget", "node", "pnpm", "bun"]) {
    fs.writeFileSync(
      path.join(fakeBin, tool),
      `#!/bin/sh\necho "test blocked ${tool}" >&2\nexit 1\n`,
      { mode: 0o755 },
    );
  }
  const result = spawnSync("sh", [INSTALLER], {
    env: { ...process.env, PATH: `${fakeBin}:${process.env.PATH}` },
    encoding: "utf8",
  });
  return { status: result.status, output: result.stdout + result.stderr };
}

describe("install.sh on Windows", () => {
  it("stops before installing anything and gives the WSL 2 and Docker Desktop steps", () => {
    const { status, output } = runOnWindowsShell();

    expect(status).toBe(1);
    expect(output).toContain("wsl --install -d Ubuntu");
    expect(output).toContain("Docker Desktop");
    expect(output).toContain("WSL integration");
    expect(output).toContain("curl -fsSL https://heygaia.io/install.sh | sh");
    expect(output).not.toContain("Node.js");
  });
});
