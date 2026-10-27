/** /.well-known/security.txt stays a valid RFC 9116 file and is renewed before it lapses. */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SECURITY_TXT = readFileSync(
  path.join(process.cwd(), "public", ".well-known", "security.txt"),
  "utf8",
);

const DAY_MS = 24 * 60 * 60 * 1000;
const RENEWAL_WINDOW_MS = 30 * DAY_MS;
// RFC 9116 §2.5.5: Expires should be less than a year ahead.
const MAX_LIFETIME_MS = 366 * DAY_MS;

function fields(name: string): string[] {
  return SECURITY_TXT.split("\n")
    .filter((line) => line.startsWith(`${name}:`))
    .map((line) => line.slice(name.length + 1).trim());
}

describe("security.txt", () => {
  it("names the security contact, policy, language and canonical URL", () => {
    expect(fields("Contact")).toEqual(["mailto:security@heygaia.io"]);
    expect(fields("Policy")).toEqual([
      "https://github.com/theexperiencecompany/gaia/security/policy",
    ]);
    expect(fields("Preferred-Languages")).toEqual(["en"]);
    expect(fields("Canonical")).toEqual([
      "https://heygaia.io/.well-known/security.txt",
    ]);
  });

  it("expires once, more than 30 days and less than a year from now", () => {
    const expires = fields("Expires");
    expect(expires).toHaveLength(1);
    const expiresAt = Date.parse(expires[0]);
    expect(Number.isNaN(expiresAt)).toBe(false);
    expect(expiresAt - Date.now()).toBeGreaterThan(RENEWAL_WINDOW_MS);
    expect(expiresAt - Date.now()).toBeLessThan(MAX_LIFETIME_MS);
  });
});
