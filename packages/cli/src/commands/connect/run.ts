// Runs the cached `gaia-connect` binary as a transparent pass-through child.
//
// `lib/interactive.ts` cannot be reused here: it collapses every non-zero exit
// into a thrown "Command failed with code N", and `gaia-connect --json` uses
// distinct exit codes that callers script against, so the code must survive.
// The SIGINT/SIGTERM handling below mirrors that module's contract: a child
// terminated by an expected signal is a clean exit, not a failure.

import { spawn } from "node:child_process";

export async function runConnectBinary(
  binary: string,
  args: string[],
): Promise<number> {
  return await new Promise<number>((resolve, reject) => {
    const child = spawn(binary, args, { stdio: "inherit", shell: false });

    const onSignal = (signal: NodeJS.Signals) => {
      child.kill(signal);
    };
    process.on("SIGINT", onSignal);
    process.on("SIGTERM", onSignal);

    child.on("error", (error) => {
      process.off("SIGINT", onSignal);
      process.off("SIGTERM", onSignal);
      reject(error);
    });

    child.on("close", (code, signal) => {
      process.off("SIGINT", onSignal);
      process.off("SIGTERM", onSignal);
      // Ctrl-C on an interactive TUI is a normal way to quit, and a
      // signal-killed child reports code === null.
      if (signal === "SIGINT" || signal === "SIGTERM") {
        resolve(0);
        return;
      }
      resolve(code ?? 1);
    });
  });
}
