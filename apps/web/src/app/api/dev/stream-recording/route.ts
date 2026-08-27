import { existsSync } from "node:fs";
import { appendFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { NextResponse } from "next/server";
import type { StreamLogEntry } from "@/lib/streamLogger";

/**
 * Dev-only sink that appends the frontend's stream log to disk as NDJSON, so a
 * coding agent can read what the browser actually received without a browser.
 * See the `reading-stream-recordings` skill.
 */

// Recording ids are minted client-side from a timestamp + random suffix; the
// pattern is what keeps them from escaping the recordings directory.
const RECORDING_ID_PATTERN = /^[A-Za-z0-9-]{1,64}$/;

interface StreamRecordingRequest {
  recordingId: string;
  entries: StreamLogEntry[];
}

function findRepoRoot(): string {
  let dir = process.cwd();
  while (!existsSync(join(dir, "pnpm-workspace.yaml"))) {
    const parent = dirname(dir);
    if (parent === dir) {
      throw new Error(
        `Could not locate the workspace root above ${process.cwd()}`,
      );
    }
    dir = parent;
  }
  return dir;
}

export async function POST(request: Request): Promise<NextResponse> {
  if (process.env.NODE_ENV === "production") {
    return new NextResponse(null, { status: 404 });
  }

  const { recordingId, entries } =
    (await request.json()) as StreamRecordingRequest;

  if (!RECORDING_ID_PATTERN.test(recordingId)) {
    return NextResponse.json({ error: "Invalid recordingId" }, { status: 400 });
  }
  if (!Array.isArray(entries) || entries.length === 0) {
    return NextResponse.json({ error: "No entries" }, { status: 400 });
  }

  const directory = join(findRepoRoot(), ".agents", "recording", "stream");
  await mkdir(directory, { recursive: true });
  const file = join(directory, `${recordingId}.ndjson`);
  await appendFile(
    file,
    `${entries.map((entry) => JSON.stringify(entry)).join("\n")}\n`,
    "utf8",
  );

  return NextResponse.json({ file, appended: entries.length });
}
