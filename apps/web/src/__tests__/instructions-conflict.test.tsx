// @vitest-environment jsdom
//
// The real hook, typed client and ApiError run against an in-memory stand-in
// for /api/v1/instructions/{scope}; only the axios transport is faked.

import { INSTRUCTIONS_CONFLICT_CODE } from "@shared/constants/instructions";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as ApiClient from "@/lib/api/client";

const request = vi.fn();
const toastError = vi.fn();
const toastSuccess = vi.fn();

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  apiauth: { request: (...args: unknown[]) => request(...args) },
  apiOrigin: "http://localhost:8000",
}));
vi.mock("@/lib/toast", () => ({
  toast: {
    error: (...args: unknown[]) => toastError(...args),
    success: (...args: unknown[]) => toastSuccess(...args),
  },
}));
vi.mock("@/lib/analytics", () => ({
  track: vi.fn(),
}));

import { useInstructions } from "@/features/instructions";

interface StoredScope {
  content: string;
  revision: number;
  updated_by: "user" | "agent" | null;
}

const server = new Map<string, StoredScope>();
const putBodies: { content: string; base_revision: number }[] = [];
let failNextPutWith: number | null = null;

const httpFailure = (status: number, data: unknown) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: {
      status,
      data,
      headers: { "content-type": "application/json" },
    },
  });

const record = (scope: string) => {
  const stored = server.get(scope) ?? {
    content: "",
    revision: 0,
    updated_by: null,
  };
  return { scope, ...stored, updated_at: null };
};

/** Mirrors write_instructions: a stale base_revision is a 409 carrying current_revision. */
const fakeInstructionsApi = async (config: {
  method: string;
  url: string;
  data?: string;
}) => {
  const scope = decodeURIComponent(config.url.split("/").pop() ?? "");
  if (config.method === "GET") {
    return { status: 200, data: record(scope), headers: {} };
  }
  const body = JSON.parse(config.data ?? "{}");
  putBodies.push(body);
  if (failNextPutWith !== null) {
    const status = failNextPutWith;
    failNextPutWith = null;
    throw httpFailure(status, { message: "Instructions are invalid" });
  }
  const current = record(scope);
  if (body.base_revision !== current.revision) {
    throw httpFailure(409, {
      message:
        "These instructions were changed somewhere else since you opened them",
      fix: "Load the latest version, or save again to overwrite it",
      code: INSTRUCTIONS_CONFLICT_CODE,
      current_revision: current.revision,
    });
  }
  server.set(scope, {
    content: body.content,
    revision: current.revision + 1,
    updated_by: "user",
  });
  return { status: 200, data: record(scope), headers: {} };
};

const agentWrites = (scope: string, content: string) => {
  const current = record(scope);
  server.set(scope, {
    content,
    revision: current.revision + 1,
    updated_by: "agent",
  });
};

const renderInstructions = (scope: string) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return {
    queryClient,
    ...renderHook(() => useInstructions(scope), { wrapper }),
  };
};

const loaded = async (scope: string) => {
  const hook = renderInstructions(scope);
  await waitFor(() => expect(hook.result.current.isLoading).toBe(false));
  return hook;
};

describe("useInstructions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.clear();
    putBodies.length = 0;
    failNextPutWith = null;
    request.mockImplementation(fakeInstructionsApi);
  });

  it("saves against the revision the editor loaded", async () => {
    server.set("global", {
      content: "Be brief",
      revision: 3,
      updated_by: "user",
    });
    const { result } = await loaded("global");

    act(() => result.current.setDraft("Be brief and kind"));
    let saved = false;
    await act(async () => {
      saved = await result.current.save();
    });

    expect(saved).toBe(true);
    expect(putBodies).toEqual([
      { content: "Be brief and kind", base_revision: 3 },
    ]);
    expect(result.current.instructions?.revision).toBe(4);
    expect(result.current.isDirty).toBe(false);
    expect(result.current.hasConflict).toBe(false);
  });

  it("surfaces a conflict and keeps the draft when GAIA saved in between", async () => {
    const { result } = await loaded("slack");
    act(() => result.current.setDraft("Focus on #eng"));
    agentWrites("slack", "Never post to #general");

    let saved = true;
    await act(async () => {
      saved = await result.current.save();
    });

    expect(saved).toBe(false);
    expect(result.current.hasConflict).toBe(true);
    expect(result.current.draft).toBe("Focus on #eng");
    expect(toastError).not.toHaveBeenCalled();
    expect(server.get("slack")?.content).toBe("Never post to #general");
  });

  it("a background refetch does not rebase an open draft past GAIA's write", async () => {
    const { result, queryClient } = await loaded("slack");
    act(() => result.current.setDraft("Focus on #eng"));
    agentWrites("slack", "Never post to #general");
    await act(async () => {
      await queryClient.refetchQueries();
    });
    await waitFor(() => expect(result.current.instructions?.revision).toBe(1));

    await act(async () => {
      await result.current.save();
    });

    expect(putBodies.map((body) => body.base_revision)).toEqual([0]);
    expect(result.current.hasConflict).toBe(true);
    expect(result.current.draft).toBe("Focus on #eng");
  });

  it("keep mine re-saves against current_revision from the conflict", async () => {
    const { result } = await loaded("slack");
    act(() => result.current.setDraft("Focus on #eng"));
    agentWrites("slack", "Never post to #general");
    agentWrites("slack", "Never post to #random either");
    await act(async () => {
      await result.current.save();
    });

    let saved = false;
    await act(async () => {
      saved = await result.current.keepMine();
    });

    expect(saved).toBe(true);
    expect(putBodies.map((body) => body.base_revision)).toEqual([0, 2]);
    expect(server.get("slack")).toEqual({
      content: "Focus on #eng",
      revision: 3,
      updated_by: "user",
    });
    expect(result.current.hasConflict).toBe(false);
  });

  it("load latest replaces the draft and rebases the next save", async () => {
    const { result } = await loaded("slack");
    act(() => result.current.setDraft("Focus on #eng"));
    agentWrites("slack", "Never post to #general");
    await act(async () => {
      await result.current.save();
    });

    await act(async () => {
      await result.current.loadLatest();
    });

    expect(result.current.hasConflict).toBe(false);
    expect(result.current.draft).toBe("Never post to #general");
    expect(result.current.isDirty).toBe(false);

    act(() => result.current.setDraft("Never post to #general. Be terse."));
    await act(async () => {
      await result.current.save();
    });
    expect(putBodies.at(-1)?.base_revision).toBe(1);
    expect(server.get("slack")?.revision).toBe(2);
  });

  it("toasts a failure that is not a conflict instead of raising one", async () => {
    const { result } = await loaded("global");
    act(() => result.current.setDraft("Be brief"));
    failNextPutWith = 400;

    let saved = true;
    await act(async () => {
      saved = await result.current.save();
    });

    expect(saved).toBe(false);
    expect(result.current.hasConflict).toBe(false);
    expect(toastError).toHaveBeenCalledWith("Instructions are invalid");
    expect(result.current.draft).toBe("Be brief");
  });
});
