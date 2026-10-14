import { describe, expect, it } from "vitest";
import {
  collectMachineSecrets,
  generateMachineSecret,
  parseAssignedEnvKeys,
} from "../../src/lib/machine-secrets.js";

describe("generateMachineSecret", () => {
  it("returns 64 hex chars (openssl rand -hex 32 equivalent)", () => {
    const secret = generateMachineSecret();
    expect(secret).toMatch(/^[0-9a-f]{64}$/);
  });

  it("generates distinct values", () => {
    const seen = new Set(
      Array.from({ length: 50 }, () => generateMachineSecret()),
    );
    expect(seen.size).toBe(50);
  });
});

describe("parseAssignedEnvKeys", () => {
  it("returns keys with non-empty values", () => {
    const content = [
      "# comment",
      "",
      "AGENT_SECRET=abc123",
      'BOT_SESSION_TOKEN_SECRET="quoted"',
      "EMPTY_VAR=",
      "NOT_AN_ASSIGNMENT",
      "=NO_KEY",
    ].join("\n");
    expect(parseAssignedEnvKeys(content)).toEqual(
      new Set(["AGENT_SECRET", "BOT_SESSION_TOKEN_SECRET"]),
    );
  });

  it("returns empty set for null or empty content", () => {
    expect(parseAssignedEnvKeys(null).size).toBe(0);
    expect(parseAssignedEnvKeys("").size).toBe(0);
  });
});

describe("collectMachineSecrets", () => {
  it("generates every secret, the instance secret included, on a fresh install", () => {
    const secrets = collectMachineSecrets(null);
    expect(Object.keys(secrets).sort()).toEqual([
      "AGENT_SECRET",
      "BOT_SESSION_TOKEN_SECRET",
      "EMAIL_UNSUBSCRIBE_SECRET",
      "GAIA_BOT_API_KEY",
      "INSTANCE_SECRET",
      "SHARE_GRANT_SECRET",
    ]);
    for (const value of Object.values(secrets)) {
      expect(value).toMatch(/^[0-9a-f]{64}$/);
    }
  });

  it("merge-don't-clobber: preserves pre-existing secrets", () => {
    const existing = [
      "ENV=selfhost",
      "AGENT_SECRET=existing-agent-secret",
      "BOT_SESSION_TOKEN_SECRET=existing-bot-secret",
      "SHARE_GRANT_SECRET=existing-share-secret",
      "GAIA_BOT_API_KEY=existing-bot-api-key",
    ].join("\n");

    const secrets = collectMachineSecrets(existing);

    // Only the missing one is generated.
    expect(Object.keys(secrets)).toEqual(["EMAIL_UNSUBSCRIBE_SECRET"]);
    expect(secrets.EMAIL_UNSUBSCRIBE_SECRET).toMatch(/^[0-9a-f]{64}$/);
  });

  it("never adds an instance secret to an existing install's .env", () => {
    const secrets = collectMachineSecrets("ENV=selfhost\n");
    expect(secrets).not.toHaveProperty("INSTANCE_SECRET");
  });

  it("treats blank values as missing and completes them", () => {
    const existing = 'AGENT_SECRET=\nBOT_SESSION_TOKEN_SECRET=""\n';
    const secrets = collectMachineSecrets(existing);
    // Both blank entries count as missing; the others were never present.
    expect(Object.keys(secrets).sort()).toEqual([
      "AGENT_SECRET",
      "BOT_SESSION_TOKEN_SECRET",
      "EMAIL_UNSUBSCRIBE_SECRET",
      "GAIA_BOT_API_KEY",
      "SHARE_GRANT_SECRET",
    ]);
  });
});
