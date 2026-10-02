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
