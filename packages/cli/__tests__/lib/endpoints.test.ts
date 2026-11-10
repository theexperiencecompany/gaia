import type { NetworkInterfaceInfo } from "node:os";
import { describe, expect, it } from "vitest";
import {
  browsesFromElsewhere,
  hostWebUrls,
  localApiUrl,
  localhostWebUrl,
  primaryWebUrl,
} from "../../src/lib/endpoints.js";

function iface(
  address: string,
  family: "IPv4" | "IPv6",
  internal: boolean,
): NetworkInterfaceInfo {
  return {
    address,
    family,
    internal,
    netmask: "",
    mac: "",
    cidr: null,
    ...(family === "IPv6" ? { scopeid: 0 } : {}),
  } as NetworkInterfaceInfo;
}

const INTERFACES = {
  lo: [iface("127.0.0.1", "IPv4", true), iface("::1", "IPv6", true)],
  eth0: [iface("192.168.64.7", "IPv4", false), iface("fe80::1", "IPv6", false)],
  docker0: [iface("172.17.0.1", "IPv4", false)],
  "br-1a2b3c": [iface("172.18.0.1", "IPv4", false)],
  wlan0: [iface("10.0.0.5", "IPv4", false)],
};

describe("hostWebUrls", () => {
  it("lists the host's non-loopback IPv4 addresses, not Docker's bridges", () => {
    expect(hostWebUrls(3000, INTERFACES)).toEqual([
      "http://192.168.64.7:3000",
      "http://10.0.0.5:3000",
    ]);
  });
});

describe("web URLs on HTTP's own port", () => {
  it("leave :80 out, as a browser shows them", () => {
    expect(hostWebUrls(80, INTERFACES)).toEqual([
      "http://192.168.64.7",
      "http://10.0.0.5",
    ]);
    expect(localhostWebUrl(80)).toBe("http://localhost");
    expect(localApiUrl("selfhost", { 3000: 80 })).toBe(
      "http://localhost/api/v1",
    );
  });
});

describe("primaryWebUrl", () => {
  it("points a browser on another machine at the host's LAN address", () => {
    expect(primaryWebUrl(3000, undefined, INTERFACES, true)).toBe(
      "http://192.168.64.7:3000",
    );
  });

  it("prefers the public domain when one is set", () => {
    expect(primaryWebUrl(80, "gaia.example.com", INTERFACES)).toBe(
      "https://gaia.example.com",
    );
  });

  it("falls back to localhost on a host with no LAN address", () => {
    expect(primaryWebUrl(3000, undefined, { lo: INTERFACES.lo }, true)).toBe(
      "http://localhost:3000",
    );
  });

  it("points a browser on this machine at localhost, the address the setup link uses", () => {
    expect(primaryWebUrl(3000, undefined, INTERFACES, false)).toBe(
      "http://localhost:3000",
    );
  });
});

describe("browsesFromElsewhere", () => {
  it("is true over SSH and on a headless Linux host, false on a desktop", () => {
    expect(browsesFromElsewhere({ SSH_CONNECTION: "1 2 3 4" }, "darwin")).toBe(
      true,
    );
    expect(browsesFromElsewhere({}, "linux")).toBe(true);
    expect(browsesFromElsewhere({ DISPLAY: ":0" }, "linux")).toBe(false);
    expect(browsesFromElsewhere({}, "darwin")).toBe(false);
  });
});
