import { describe, expect, it } from "vitest";
import {
  aptInstallPackages,
  describeDpkgLine,
  sumPrintUris,
} from "../../src/lib/apt-activity.js";

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

// The line get.docker.com traces (set -x) before its install, verbatim.
const DOCKER_INSTALL_LINE =
  "+ sh -c DEBIAN_FRONTEND=noninteractive apt-get -y -qq install docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-ce-rootless-extras docker-buildx-plugin docker-model-plugin >/dev/null";

describe("aptInstallPackages", () => {
  it("reads the packages an apt-get install line names, without its options or redirect", () => {
    expect(aptInstallPackages(DOCKER_INSTALL_LINE)).toEqual([
      "docker-ce",
      "docker-ce-cli",
      "containerd.io",
      "docker-compose-plugin",
      "docker-ce-rootless-extras",
      "docker-buildx-plugin",
      "docker-model-plugin",
    ]);
  });

  it("names nothing for a line that is not an install", () => {
    expect(
      aptInstallPackages("+ sh -c apt-get -qq update >/dev/null"),
    ).toBeNull();
  });
});

describe("sumPrintUris", () => {
  // `apt-get install --print-uris -qq` output: one quoted URL, file, size and hash per package.
  it("adds up the sizes apt would download", () => {
    expect(
      sumPrintUris(
        [
          "'https://download.docker.com/linux/ubuntu/dists/noble/pool/stable/arm64/containerd.io_2.1.4-1_arm64.deb' containerd.io_2.1.4-1_arm64.deb 21318842 SHA256:aa",
          "'https://download.docker.com/linux/ubuntu/dists/noble/pool/stable/arm64/docker-ce_28.5.1-1_arm64.deb' docker-ce_28.5.1-1_arm64.deb 17043360 SHA256:bb",
          "",
        ].join("\n"),
      ),
    ).toBe(21_318_842 + 17_043_360);
  });

  it("is zero when everything is already downloaded", () => {
    expect(sumPrintUris("")).toBe(0);
  });
});
