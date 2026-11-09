import { describe, expect, it } from "vitest";
import { needsLocalCertificate } from "../../src/lib/local-certificate.js";

describe("needsLocalCertificate", () => {
  it("is true for names no public certificate authority can certify", () => {
    for (const domain of [
      "gaia.test",
      "GAIA.TEST",
      "gaia.localhost",
      "gaia.local",
      "gaia.internal",
      "nas.home.arpa",
      "gaia.example",
      "gaia.invalid",
    ]) {
      expect(needsLocalCertificate(domain)).toBe(true);
    }
  });

  it("is false for public domains, including ones that only contain a reserved word", () => {
    for (const domain of ["gaia.example.com", "test.com", "my.testing.io"]) {
      expect(needsLocalCertificate(domain)).toBe(false);
    }
  });
});
