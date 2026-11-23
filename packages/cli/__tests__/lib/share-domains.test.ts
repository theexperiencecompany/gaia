import { describe, expect, it } from "vitest";
import {
  applyShareDomainApiEnv,
  resolveShareDomains,
  SHARE_DOMAIN_INPUT,
} from "../../src/lib/share-domains.js";
import { createStore } from "../../src/ui/store.js";

const SIGNING_KEY = /^[0-9a-f]{64}$/;

describe("applyShareDomainApiEnv", () => {
  it("points minted links at the link domain and files at the content host", () => {
    const env: Record<string, string> = {};

    applyShareDomainApiEnv(env, {
      link: "go.example.com",
      usercontent: "files.example.com",
    });

    expect(env["SHORTLINK_BASE_URL"]).toBe("https://go.example.com");
    expect(env["LINK_CONTENT_URL_TEMPLATE"]).toBe(
      "https://files.example.com/api/v1/usercontent/{content_id}",
    );
    expect(env["LINK_CONTENT_SIGNING_KEY"]).toMatch(SIGNING_KEY);
  });

  it("keeps the signing key an earlier run generated", () => {
    const env = { LINK_CONTENT_SIGNING_KEY: "a".repeat(64) };

    applyShareDomainApiEnv(env, { usercontent: "files.example.com" });

    expect(env.LINK_CONTENT_SIGNING_KEY).toBe("a".repeat(64));
  });

  it("drops every share setting when neither domain is set", () => {
    const env: Record<string, string> = {
      SHORTLINK_BASE_URL: "https://go.example.com",
      LINK_CONTENT_URL_TEMPLATE:
        "https://files.example.com/api/v1/usercontent/{content_id}",
      LINK_CONTENT_SIGNING_KEY: "a".repeat(64),
      FRONTEND_URL: "https://gaia.example.com",
    };

    applyShareDomainApiEnv(env, {});

    expect(env).toEqual({ FRONTEND_URL: "https://gaia.example.com" });
  });
});

describe("resolveShareDomains", () => {
  it("serves none without a GAIA domain, even when one was recorded", async () => {
    const domains = await resolveShareDomains(createStore(), {
      appDomain: undefined,
      flags: {},
      recorded: { link: "go.example.com" },
      canAsk: true,
    });

    expect(domains).toEqual({});
  });

  it("refuses a share-domain flag on an install with no GAIA domain", async () => {
    await expect(
      resolveShareDomains(createStore(), {
        appDomain: undefined,
        flags: { link: "go.example.com" },
        recorded: {},
        canAsk: false,
      }),
    ).rejects.toThrow(/--domain/);
  });

  it("takes a flag over the recorded value, and false drops it", async () => {
    const domains = await resolveShareDomains(createStore(), {
      appDomain: "gaia.example.com",
      flags: { link: "s.example.com", usercontent: false },
      recorded: { link: "go.example.com", usercontent: "files.example.com" },
      canAsk: true,
    });

    expect(domains).toEqual({ link: "s.example.com" });
  });

  it("keeps the recorded domains without asking", async () => {
    const store = createStore();
    const asked: string[] = [];
    store.pushAnswerResolver({
      [SHARE_DOMAIN_INPUT]: ({ kind }) => {
        asked.push(kind);
        return "";
      },
    });

    const domains = await resolveShareDomains(store, {
      appDomain: "gaia.example.com",
      flags: {},
      recorded: { link: "go.example.com", usercontent: "files.example.com" },
      canAsk: true,
    });

    expect(domains).toEqual({
      link: "go.example.com",
      usercontent: "files.example.com",
    });
    expect(asked).toEqual([]);
  });

  it("asks for each undecided domain when a person can answer, and an empty answer skips it", async () => {
    const store = createStore();
    store.pushAnswerResolver({
      [SHARE_DOMAIN_INPUT]: ({ kind }) =>
        kind === "link" ? " Go.Example.com " : "",
    });

    const domains = await resolveShareDomains(store, {
      appDomain: "gaia.example.com",
      flags: {},
      recorded: {},
      canAsk: true,
    });

    expect(domains).toEqual({ link: "go.example.com" });
  });

  it("asks nothing in a run no one can answer", async () => {
    const store = createStore();
    let asked = false;
    store.pushAnswerResolver({
      [SHARE_DOMAIN_INPUT]: () => {
        asked = true;
        return "go.example.com";
      },
    });

    const domains = await resolveShareDomains(store, {
      appDomain: "gaia.example.com",
      flags: {},
      recorded: {},
      canAsk: false,
    });

    expect(domains).toEqual({});
    expect(asked).toBe(false);
  });

  it("asks again, saying why, when an answer is not a usable host", async () => {
    const store = createStore();
    const retries = new Set<string | undefined>();
    // A values layer answers the same request the same way, however often it is consulted.
    store.pushAnswerResolver({
      [SHARE_DOMAIN_INPUT]: ({ kind, retry }) => {
        if (kind !== "link") return "";
        retries.add(retry);
        if (retry === undefined) return "https://go.example.com/x";
        return retry.includes("domain name")
          ? "gaia.example.com"
          : "go.example.com";
      },
    });

    const domains = await resolveShareDomains(store, {
      appDomain: "gaia.example.com",
      flags: {},
      recorded: {},
      canAsk: true,
    });

    expect(domains).toEqual({ link: "go.example.com" });
    const [first, second, third] = [...retries];
    expect(first).toBeUndefined();
    expect(second).toMatch(/domain name/);
    expect(third).toMatch(/GAIA itself/);
  });

  it("refuses a flag that names GAIA's own domain or the other share domain", async () => {
    await expect(
      resolveShareDomains(createStore(), {
        appDomain: "gaia.example.com",
        flags: { usercontent: "gaia.example.com" },
        recorded: {},
        canAsk: false,
      }),
    ).rejects.toThrow(/GAIA itself/);
    await expect(
      resolveShareDomains(createStore(), {
        appDomain: "gaia.example.com",
        flags: { link: "s.example.com", usercontent: "s.example.com" },
        recorded: {},
        canAsk: false,
      }),
    ).rejects.toThrow(/different/);
  });
});
