import type { NetworkInterfaceInfo } from "node:os";
import { describe, expect, it } from "vitest";
import { reachableWebUrls } from "../../src/lib/endpoints.js";

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

describe("reachableWebUrls", () => {
  it("lists localhost plus the host's non-loopback IPv4 addresses, not Docker's bridges", () => {
    expect(reachableWebUrls(3000, undefined, INTERFACES)).toEqual([
      "http://localhost:3000",
      "http://192.168.64.7:3000",
      "http://10.0.0.5:3000",
    ]);
  });

  it("leads with the public https origin when a domain is set", () => {
    expect(reachableWebUrls(80, "gaia.example.com", INTERFACES)).toEqual([
      "https://gaia.example.com",
      "http://localhost:80",
      "http://192.168.64.7:80",
      "http://10.0.0.5:80",
    ]);
  });
});
