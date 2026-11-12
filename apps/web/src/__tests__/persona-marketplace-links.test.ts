/**
 * Persona pages link each relevant integration to its marketplace page, so every
 * slug a persona lists must be one the marketplace serves (recorded from prod
 * /integrations/config), and an unknown slug must fail the render, not 404.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resolvePersonaIntegrations } from "@/features/personas/data/personaIntegrations";
import { getAllPersonas } from "@/features/personas/data/personasData";

import MARKETPLACE_CONFIG from "./fixtures/integrations-config.json";

const MARKETPLACE_SLUGS = new Set(
  MARKETPLACE_CONFIG.integrations.map((integration) => integration.slug),
);

function stubMarketplaceBackend(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) =>
      Response.json(
        input.url.includes("/integrations/config")
          ? MARKETPLACE_CONFIG
          : { integrations: [], total: 0 },
      ),
    ),
  );
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.stubEnv("API_BASE_URL_INTERNAL", "http://api.test/api/v1");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("persona marketplace links", () => {
  it("lists only slugs the marketplace serves", async () => {
    const personas = await getAllPersonas();
    expect(personas.length).toBeGreaterThan(0);
    const unknown = personas.flatMap((persona) =>
      persona.relevantIntegrations
        .filter((slug) => !MARKETPLACE_SLUGS.has(slug))
        .map((slug) => `${persona.slug}: ${slug}`),
    );
    expect(unknown).toEqual([]);
  });

  it("resolves every persona's integrations to their marketplace records", async () => {
    vi.setSystemTime(new Date("2040-01-01T00:00:00Z"));
    stubMarketplaceBackend();

    for (const persona of await getAllPersonas()) {
      const integrations = await resolvePersonaIntegrations(persona);
      expect(integrations.map((integration) => integration.slug)).toEqual(
        persona.relevantIntegrations,
      );
    }
    const [calendar] = await resolvePersonaIntegrations({
      slug: "test",
      relevantIntegrations: ["googlecalendar"],
    });
    expect(calendar?.name).toBe("Google Calendar");
  });

  it("fails the render on a slug the marketplace does not serve", async () => {
    vi.setSystemTime(new Date("2041-01-01T00:00:00Z"));
    stubMarketplaceBackend();

    await expect(
      resolvePersonaIntegrations({
        slug: "consultants",
        relevantIntegrations: ["gmail", "google-calendar"],
      }),
    ).rejects.toThrow(/consultants.*google-calendar/);
  });
});
