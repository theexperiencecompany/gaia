import { createTodoStore, type TodoApiClient } from "@shared/todos";
import { describe, expect, it, vi } from "vitest";
import type { Todo } from "@/types/features/todoTypes";

import { makeTodo } from "./fixtures/todo";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeApi() {
  return {
    getAllTodos: vi.fn(async (_filters?: unknown): Promise<Todo[]> => []),
    getAllProjects: vi.fn(async () => []),
    getAllLabels: vi.fn(async () => []),
    getTodoCounts: vi.fn(async () => ({
      inbox: 0,
      today: 0,
      upcoming: 0,
      completed: 0,
      overdue: 0,
    })),
  } as unknown as TodoApiClient;
}

describe("todo store loading", () => {
  it("last writer wins when filter changes outrun the first load", async () => {
    const api = makeApi();
    const inboxGate = deferred<Todo[]>();
    const labelGate = deferred<Todo[]>();
    const inboxTodos = [makeTodo("inbox-1")];
    const labelTodos = [makeTodo("label-1")];
    api.getAllTodos = vi
      .fn()
      .mockImplementationOnce(() => inboxGate.promise)
      .mockImplementationOnce(() => labelGate.promise);

    const useStore = createTodoStore(api);
    const first = useStore.getState().loadTodos({ completed: false });
    const second = useStore.getState().loadTodos({ labels: ["x"] });

    // The newer (label) request resolves first, then the stale inbox one.
    labelGate.resolve(labelTodos);
    await second;
    inboxGate.resolve(inboxTodos);
    await first;

    expect(useStore.getState().todos).toEqual(labelTodos);
    expect(useStore.getState().initialLoading).toBe(false);
  });

  it("shares one in-flight request when consumers mount together", async () => {
    const api = makeApi();
    const gate = deferred<never[]>();
    api.getAllProjects = vi.fn(() => gate.promise);

    const useStore = createTodoStore(api);
    const first = useStore.getState().loadProjects();
    const second = useStore.getState().loadProjects();
    gate.resolve([]);
    await Promise.all([first, second]);

    expect(api.getAllProjects).toHaveBeenCalledTimes(1);
  });

  it("refreshAll covers labels alongside todos, projects and counts", async () => {
    const api = makeApi();
    const useStore = createTodoStore(api);
    await useStore.getState().refreshAll({ completed: false });

    expect(api.getAllTodos).toHaveBeenCalledTimes(1);
    expect(api.getAllProjects).toHaveBeenCalledTimes(1);
    expect(api.getAllLabels).toHaveBeenCalledTimes(1);
    expect(api.getTodoCounts).toHaveBeenCalledTimes(1);
  });

  it("a write refreshes totals with a fresh read, not the stale in-flight one", async () => {
    const api = makeApi();
    const staleGate = deferred<{
      inbox: number;
      today: number;
      upcoming: number;
      completed: number;
      overdue: number;
    }>();
    const freshCounts = {
      inbox: 4,
      today: 0,
      upcoming: 0,
      completed: 1,
      overdue: 0,
    };
    api.getTodoCounts = vi
      .fn()
      .mockImplementationOnce(() => staleGate.promise)
      .mockImplementation(async () => freshCounts);
    const todo = makeTodo("t1");
    api.updateTodo = vi.fn(async () => todo);
    const useStore = createTodoStore(api);
    useStore.getState().setTodos([todo]);

    const loading = useStore.getState().loadCounts();
    await useStore.getState().updateTodo("t1", { completed: true });
    staleGate.resolve({
      inbox: 5,
      today: 0,
      upcoming: 0,
      completed: 0,
      overdue: 0,
    });
    await loading;

    expect(api.getTodoCounts).toHaveBeenCalledTimes(2);
    expect(useStore.getState().counts).toEqual(freshCounts);
  });

  it("a failed write rolls back without masquerading as a failed load", async () => {
    const api = makeApi();
    const todo = makeTodo("t1");
    api.updateTodo = vi.fn(async () => {
      throw new Error("boom");
    });
    const useStore = createTodoStore(api);
    useStore.getState().setTodos([todo]);

    await expect(
      useStore.getState().updateTodo("t1", { completed: true }),
    ).rejects.toThrow("boom");

    expect(useStore.getState().todos).toEqual([todo]);
    expect(useStore.getState().error).toBeNull();
  });
});
