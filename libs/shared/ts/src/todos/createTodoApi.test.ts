import { describe, expect, it } from "vitest";

import { createTodoApi, type HttpAdapter } from "./createTodoApi";

function recordingHttp(): { http: HttpAdapter; urls: string[] } {
  const urls: string[] = [];
  async function answer<T>(url: string): Promise<T> {
    urls.push(url);
    return [] as T;
  }
  return {
    http: {
      get: answer,
      post: answer,
      put: answer,
      patch: answer,
      delete: answer,
    },
    urls,
  };
}

describe("getAllTodos paging", () => {
  it("asks the list endpoint for the page its skip and limit describe", async () => {
    const { http, urls } = recordingHttp();

    await createTodoApi(http).getAllTodos({
      parent_todo_id: "desk",
      skip: 100,
      limit: 50,
    });

    const query = new URLSearchParams(urls[0].split("?")[1]);
    expect(Object.fromEntries(query)).toEqual({
      parent_todo_id: "desk",
      page: "3",
      per_page: "50",
    });
  });

  it("without a limit leaves paging to the endpoint", async () => {
    const { http, urls } = recordingHttp();

    await createTodoApi(http).getAllTodos({ completed: true });

    expect(
      Object.fromEntries(new URLSearchParams(urls[0].split("?")[1])),
    ).toEqual({
      completed: "true",
    });
  });
});

describe("openTodoConversation", () => {
  it("asks the todo's own chat endpoint and hands back its conversation", async () => {
    const calls: Array<{ method: string; url: string }> = [];
    async function answer<T>(url: string): Promise<T> {
      calls.push({ method: "post", url });
      return { conversation_id: "conv-todo" } as T;
    }
    const unexpected = async <T>(url: string): Promise<T> => {
      throw new Error(`unexpected request to ${url}`);
    };

    const result = await createTodoApi({
      get: unexpected,
      post: answer,
      put: unexpected,
      patch: unexpected,
      delete: unexpected,
    }).openTodoConversation("todo-1");

    // POST, not GET: the first open creates the chat.
    expect(calls).toEqual([
      { method: "post", url: "/todos/todo-1/conversation" },
    ]);
    expect(result).toEqual({ conversation_id: "conv-todo" });
  });
});
