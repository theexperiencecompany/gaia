import { describe, expect, it } from "vitest";
import { ChatStreamFrameSchema } from "./schema";

// Verbatim `bash_data` frames captured off the wire, one per emit site in
// `apps/api/app/agents/tools/coding/bash_tool.py`. They arrive top-level (the
// chat pipeline only unwraps `tool_data`), so an unmodeled shape here is what
// made a plain `bash` turn log a schema error for every output chunk.
const bashFrames = [
  {
    bash_data: {
      id: "378840c7a016",
      command: "cat > artifacts/notes.md << 'EOF'\n- one\nEOF",
      cwd: "/workspace/sessions/f938134c",
      status: "starting",
      session_id: "f938134c",
    },
  },
  {
    bash_data: {
      id: "378840c7a016",
      status: "running",
      stream: "stderr",
      chunk: "No such file or directory\n",
      session_id: "f938134c",
    },
  },
  {
    bash_data: {
      id: "378840c7a016",
      status: "exited",
      exit_code: 1,
      session_id: "f938134c",
    },
  },
  {
    bash_data: {
      id: "378840c7a016",
      status: "error",
      exit_code: null,
      stream: "stderr",
      chunk: "sandbox unavailable",
      session_id: "f938134c",
    },
  },
  {
    bash_data: {
      id: "378840c7a016",
      status: "background_started",
      pid: "412",
      log_path: "/workspace/runs/378840c7a016.log",
      session_id: "f938134c",
    },
  },
];

// One per `file_data` emit site: write_tool, edit_tool, and read_tool's text
// and image branches.
const fileFrames = [
  {
    file_data: { operation: "write", path: "/workspace/a.md", size_bytes: 76 },
  },
  {
    file_data: {
      operation: "edit",
      path: "/workspace/a.md",
      size_bytes: 80,
      occurrences_replaced: 1,
    },
  },
  {
    file_data: {
      operation: "read",
      path: "/workspace/a.md",
      lines_returned: 3,
    },
  },
  {
    file_data: {
      operation: "read",
      path: "/workspace/a.png",
      bytes: 2048,
      mime_type: "image/png",
    },
  },
];

describe("ChatStreamFrameSchema", () => {
  it.each(bashFrames)(
    "accepts the bash_data frame $bash_data.status",
    (frame) => {
      expect(ChatStreamFrameSchema.safeParse(frame).success).toBe(true);
    },
  );

  it.each(fileFrames)(
    "accepts the file_data frame $file_data.operation",
    (frame) => {
      expect(ChatStreamFrameSchema.safeParse(frame).success).toBe(true);
    },
  );

  it("still rejects a bash_data payload with no run id", () => {
    expect(
      ChatStreamFrameSchema.safeParse({ bash_data: { status: "running" } })
        .success,
    ).toBe(false);
  });
});
