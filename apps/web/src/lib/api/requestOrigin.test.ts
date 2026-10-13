// @vitest-environment jsdom
/**
 * A request no user action caused says so, through either client, so the
 * server never counts an idle tab's poll as its user being active.
 */

import type { InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { apiauth } from "@/lib/api/client";
import { apiService } from "@/lib/api/service";
import { api } from "@/lib/api/typed";

const ORIGIN_HEADER = "X-GAIA-Request-Origin";

let sent: InternalAxiosRequestConfig[] = [];
const realAdapter = apiauth.defaults.adapter;

beforeEach(() => {
  sent = [];
  apiauth.defaults.adapter = async (config) => {
    sent.push(config);
    return {
      data: {},
      status: 200,
      statusText: "OK",
      headers: { "content-type": "application/json" },
      config,
    };
  };
});

afterEach(() => {
  apiauth.defaults.adapter = realAdapter;
});

describe("background requests", () => {
  it("are marked through the typed client", async () => {
    await api.get("/api/v1/device/list", { background: true });

    expect(sent[0]?.headers.get(ORIGIN_HEADER)).toBe("background");
  });

  it("are marked through the URL-string client", async () => {
    await apiService.get("/todos/t1/workflow-status", { background: true });

    expect(sent[0]?.headers.get(ORIGIN_HEADER)).toBe("background");
  });

  it("leave a user's own request unmarked", async () => {
    await api.get("/api/v1/device/list");
    await apiService.get("/todos/t1/workflow-status");

    expect(sent.map((config) => config.headers.get(ORIGIN_HEADER))).toEqual([
      undefined,
      undefined,
    ]);
  });
});
