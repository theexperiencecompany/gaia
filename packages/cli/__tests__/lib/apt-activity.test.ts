import { describe, expect, it } from "vitest";
import { describeDpkgLine } from "../../src/lib/apt-activity.js";

// Lines verbatim from /var/log/dpkg.log during Docker's install on Ubuntu 26.04.
describe("describeDpkgLine", () => {
  it("names the package dpkg is unpacking or setting up, without its arch or version", () => {
    expect(
      describeDpkgLine(
        "2026-10-18 03:48:31 unpack containerd.io:arm64 2.4.2-2~ubuntu.26.04~resolute <none>",
      ),
    ).toBe("unpacking containerd.io");
    expect(
      describeDpkgLine(
        "2026-10-18 03:48:43 configure docker-ce:arm64 5:29.9.1-1~ubuntu.26.04~resolute <none>",
      ),
    ).toBe("setting up docker-ce");
  });

  it("ignores the status bookkeeping lines between package steps", () => {
    expect(
      describeDpkgLine(
        "2026-10-18 03:50:48 status installed docker-ce:arm64 5:29.9.1-1~ubuntu.26.04~resolute",
      ),
    ).toBeNull();
    expect(
      describeDpkgLine("2026-10-18 03:48:40 startup packages configure"),
    ).toBeNull();
  });
});
