import { describe, expect, it } from "vitest";
import { maskSecret } from "../../src/lib/prompt.js";

describe("maskSecret", () => {
  it("shows a long token's last four characters so a paste can be checked", () => {
    expect(maskSecret("123456:ABCdefGHI")).toBe("••••••••••••fGHI");
  });

  it("hides a short secret entirely", () => {
    expect(maskSecret("abcd1234")).toBe("••••••••");
  });
});
