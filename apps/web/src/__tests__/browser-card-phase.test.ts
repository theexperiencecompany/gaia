/**
 * The chat card, the side panel and the task history all read one derived
 * status: waiting on the user while a handoff is pending, ended (nothing left
 * to watch or act on) the moment the run reports a terminal status.
 */

import { describe, expect, it } from "vitest";
import { browserCardPhase, foldBrowserTask } from "@/features/browser/utils";
import type { BrowserTaskSnapshot } from "@/types/features/browserTaskTypes";

const running: BrowserTaskSnapshot = {
  kind: "session",
  task: "Book a table",
  status: "running",
  session_id: "s1",
};

const phaseOf = (snapshots: BrowserTaskSnapshot[]) =>
  browserCardPhase(foldBrowserTask(snapshots));

describe("browserCardPhase", () => {
  it("is working while the agent drives", () => {
    expect(phaseOf([running])).toEqual({
      status: "running",
      ended: false,
      working: true,
    });
  });

  it("waits on the user, not working, while a handoff is pending", () => {
    expect(
      phaseOf([
        running,
        {
          kind: "handoff",
          handoff_id: "h1",
          reason: "Sign in to continue",
          status: "pending",
        },
      ]),
    ).toEqual({ status: "awaiting_user", ended: false, working: false });
  });

  it("has ended once the session reports a terminal status, result or not", () => {
    expect(phaseOf([{ ...running, status: "failed" }])).toEqual({
      status: "failed",
      ended: true,
      working: false,
    });
  });
});
