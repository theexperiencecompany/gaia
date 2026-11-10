import { ApiError } from "@gaia/shared";
import type { InstructionsResponse } from "@gaia/shared/api/generated";
import { INSTRUCTIONS_CONFLICT_CODE } from "@gaia/shared/constants/instructions";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { settingsApi } from "./settings-api";

const { putMock } = vi.hoisted(() => ({ putMock: vi.fn() }));

vi.mock("@/lib/api", async () => {
  const actual =
    await vi.importActual<typeof import("@gaia/shared")>("@gaia/shared");
  return {
    ApiError: actual.ApiError,
    apiService: { put: putMock },
  };
});

const SAVED: InstructionsResponse = {
  scope: "global",
  content: "Reply in British English.",
  revision: 4,
  updated_by: "user",
  updated_at: "2026-10-08T10:00:00Z",
};

describe("settingsApi.updateInstructions", () => {
  beforeEach(() => {
    putMock.mockReset();
  });

  it("sends the loaded revision as base_revision and returns the saved record", async () => {
    putMock.mockResolvedValue(SAVED);

    const result = await settingsApi.updateInstructions("global", {
      content: SAVED.content,
      base_revision: 3,
    });

    expect(putMock).toHaveBeenCalledWith("/instructions/global", {
      content: SAVED.content,
      base_revision: 3,
    });
    expect(result).toEqual({ status: "saved", instructions: SAVED });
  });

  it("maps a revision conflict to the server's current revision", async () => {
    putMock.mockRejectedValue(
      ApiError.fromBody(409, {
        message: "These instructions were changed somewhere else",
        code: INSTRUCTIONS_CONFLICT_CODE,
        current_revision: 7,
      }),
    );

    const result = await settingsApi.updateInstructions("global", {
      content: "mine",
      base_revision: 3,
    });

    expect(result).toEqual({ status: "conflict", currentRevision: 7 });
  });

  it("re-throws a 409 that carries no current revision instead of guessing one", async () => {
    putMock.mockRejectedValue(
      ApiError.fromBody(409, {
        message: "Conflict",
        code: INSTRUCTIONS_CONFLICT_CODE,
      }),
    );

    await expect(
      settingsApi.updateInstructions("global", {
        content: "mine",
        base_revision: 3,
      }),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("re-throws a non-conflict failure", async () => {
    putMock.mockRejectedValue(
      ApiError.fromBody(400, {
        message: "Instructions must be 8000 characters or less",
      }),
    );

    await expect(
      settingsApi.updateInstructions("global", {
        content: "mine",
        base_revision: 3,
      }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
