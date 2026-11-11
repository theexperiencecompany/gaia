import { describe, expect, it } from "vitest";
import {
  defaultRouteDevice,
  ipv6PublisherUnit,
  stableIpv6,
} from "../../src/lib/local-name-ipv6.js";

const ADDRS = [
  "2: eth0    inet6 2a02:8071:1:2::temp/64 scope global temporary dynamic \\       valid_lft 86000sec preferred_lft 14000sec",
  "2: eth0    inet6 2a02:8071:1:2:ec08:42ff:fea5:c96f/64 scope global dynamic mngtmpaddr noprefixroute \\       valid_lft 86000sec preferred_lft 14000sec",
  "2: eth0    inet6 2a02:8071:1:2::old/64 scope global deprecated dynamic \\       valid_lft 600sec preferred_lft 0sec",
  "3: docker0    inet6 fd00:dead::1/64 scope global \\       valid_lft forever preferred_lft forever",
  "4: wlan0    inet6 fd07:b51a:cc66:0:1::5/64 scope global \\       valid_lft forever preferred_lft forever",
].join("\n");

describe("stableIpv6", () => {
  it("picks the stable address on the default route's interface, skipping temporary and deprecated ones", () => {
    expect(stableIpv6(ADDRS, "eth0")).toBe("2a02:8071:1:2:ec08:42ff:fea5:c96f");
  });

  it("uses another interface's address when the default route's has none", () => {
    const otherOnly = ADDRS.split("\n").slice(3).join("\n");
    expect(stableIpv6(otherOnly, "eth0")).toBe("fd07:b51a:cc66:0:1::5");
  });

  it("never announces Docker's bridge addresses", () => {
    expect(
      stableIpv6(
        "3: docker0    inet6 fd00:dead::1/64 scope global \\       valid_lft forever",
        "docker0",
      ),
    ).toBeNull();
  });

  it("is null on a host with no routable IPv6 address", () => {
    expect(stableIpv6("", "eth0")).toBeNull();
  });
});

describe("defaultRouteDevice", () => {
  it("reads the interface of the default IPv4 route", () => {
    expect(
      defaultRouteDevice(
        "default via 192.168.139.1 dev eth0 proto dhcp src 192.168.139.85 metric 100",
      ),
    ).toBe("eth0");
    expect(defaultRouteDevice("")).toBeNull();
  });
});

describe("ipv6PublisherUnit", () => {
  it("publishes the AAAA record with avahi, after avahi, at every boot", () => {
    const unit = ipv6PublisherUnit(
      "/usr/bin/avahi-publish-address",
      "gaia.local",
      "fd07::5",
    );

    expect(unit).toContain(
      "ExecStart=/usr/bin/avahi-publish-address -R gaia.local fd07::5",
    );
    expect(unit).toContain("Requires=avahi-daemon.service");
    expect(unit).toContain("WantedBy=multi-user.target");
  });
});
