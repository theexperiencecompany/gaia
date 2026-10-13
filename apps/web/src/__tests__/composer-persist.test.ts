// @vitest-environment jsdom
//
// Only the draft survives a reload. A workflow or calendar selection that
// outlives the session can auto-send something the user never meant to, so
// neither is persisted, and a version-1 blob that still carries them is
// stripped on the way in.
import { describe, expect, it } from "vitest";

import { migrateComposerState } from "@/stores/composerStore";

const v1Blob = {
  inputText: "draft",
  pendingPrompt: null,
  useDefaultModels: true,
  commsModel: null,
  executorModel: null,
  selectedWorkflow: { id: "wf-1", title: "Morning brief" },
  workflowAutoSend: true,
  selectedCalendarEvent: { id: "evt-1", title: "Standup" },
};

describe("composer persistence", () => {
  it("drops the selections from a version-1 blob and keeps the draft", () => {
    const migrated = migrateComposerState(v1Blob, 1);
    expect(migrated).toEqual({
      inputText: "draft",
      pendingPrompt: null,
      useDefaultModels: true,
      commsModel: null,
      executorModel: null,
    });
    expect(migrated).not.toHaveProperty("selectedWorkflow");
    expect(migrated).not.toHaveProperty("workflowAutoSend");
    expect(migrated).not.toHaveProperty("selectedCalendarEvent");
  });

  it("passes a current-version blob through untouched", () => {
    const current = { ...v1Blob };
    expect(migrateComposerState(current, 2)).toBe(current);
  });

  it("does not persist a selection made in this session", async () => {
    const { useComposerStore } = await import("@/stores/composerStore");
    useComposerStore.getState().setInputText("hello");
    useComposerStore
      .getState()
      .selectWorkflow({ id: "wf-1", title: "Morning brief" } as never, {
        autoSend: true,
      });
    const stored = JSON.parse(
      globalThis.localStorage.getItem("composer-storage") ?? "{}",
    ) as { state?: Record<string, unknown>; version?: number };
    expect(stored.version).toBe(2);
    expect(stored.state?.inputText).toBe("hello");
    expect(stored.state).not.toHaveProperty("selectedWorkflow");
    expect(stored.state).not.toHaveProperty("workflowAutoSend");
    expect(stored.state).not.toHaveProperty("selectedCalendarEvent");
  });
});
