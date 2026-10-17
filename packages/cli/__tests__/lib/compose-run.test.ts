import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

// Real child processes: a fake `docker` on PATH prints what Compose prints.
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-compose-"));
vi.mock("../../src/lib/logs.js", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  newLogPath: (name: string) => path.join(dir, `${name}.log`),
}));

import { ComposeError } from "../../src/lib/compose-failure.js";
import type { ComposePhase } from "../../src/lib/compose-progress.js";
import { runCompose } from "../../src/lib/compose-run.js";

const PULL_EVENTS = [
  '{"id":"Image ghcr.io/theexperiencecompany/gaia-web:latest","status":"Working","text":"Pulling"}',
  '{"id":"Image ghcr.io/theexperiencecompany/gaia-web:latest","status":"Error","text":"Error","details":"no matching manifest for linux/arm64/v8 in the manifest list entries"}',
  '{"error":true,"message":"Error response from daemon: no matching manifest for linux/arm64/v8 in the manifest list entries"}',
];

const FAKE_DOCKER = `#!/bin/sh
if [ "$2" = "version" ]; then echo "2.40.3"; exit 0; fi
echo "$@" > "${dir}/args"
cat "${dir}/events" >&2
exit "$(cat "${dir}/exit")"
`;

let savedPath: string | undefined;

beforeAll(() => {
  fs.writeFileSync(path.join(dir, "docker"), FAKE_DOCKER, { mode: 0o755 });
  savedPath = process.env.PATH;
  process.env.PATH = `${dir}:${savedPath}`;
});

afterAll(() => {
  process.env.PATH = savedPath;
  fs.rmSync(dir, { recursive: true, force: true });
});

function compose(events: string[], exitCode: number) {
  fs.writeFileSync(path.join(dir, "events"), `${events.join("\n")}\n`);
  fs.writeFileSync(path.join(dir, "exit"), String(exitCode));
  const phases: ComposePhase[] = [];
  const run = runCompose(["-f", "docker-compose.selfhost.yml", "up", "-d"], {
    cwd: dir,
    logName: "compose-up",
    rebuildCommand: "gaia up --build",
    onProgress: (phase) => phases.push(phase),
  });
  return { run, phases };
}

describe("runCompose", () => {
  it("asks compose for JSON progress and reports phases, not raw lines", async () => {
    const { run, phases } = compose(
      [
        '{"id":"Container gaia-selfhost-proxy-1","status":"Working","text":"Starting"}',
        '{"id":"Container gaia-selfhost-proxy-1","status":"Done","text":"Started"}',
      ],
      0,
    );

    await run;

    expect(fs.readFileSync(path.join(dir, "args"), "utf-8")).toMatch(
      /^compose --progress json -f docker-compose.selfhost.yml up -d/,
    );
    expect(phases.at(-1)?.label).toBe("Starting GAIA: 1 of 1 services started");
  });

  it("fails with the plain cause and the log path, the raw output kept in the log", async () => {
    const { run } = compose(PULL_EVENTS, 1);

    const error = await run.catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ComposeError);
    const message = (error as ComposeError).message;
    expect(message.split("\n")[0]).toBe(
      "GAIA's web app image (gaia-web) at latest has no build for this computer's processor (arm64).",
    );
    expect(message).toContain(`Full log: ${path.join(dir, "compose-up.log")}`);
    expect(message).not.toContain('"status"');
    expect(
      fs.readFileSync(path.join(dir, "compose-up.log"), "utf-8"),
    ).toContain("no matching manifest");
  });
});
