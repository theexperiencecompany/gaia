import { existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { appConfig, footerSections } from "@/config/appConfig";
import { BOT_LINKS, BOTS } from "@/features/bots/constants";

import {
  VANITY_REDIRECT_PAIRS,
  vanityTarget,
} from "../../vanity-redirects.mjs";

const VANITY_PATHS = new Set(VANITY_REDIRECT_PAIRS.map(([source]) => source));
const BOT_INSTALL_ROUTES = ["/slack-bot", "/discord-bot"];

const landingPage = (route: string) =>
  path.join(process.cwd(), "src/app/[locale]/(landing)", route, "page.tsx");

const navAndFooterHrefs = [
  ...Object.values(appConfig.links).flat(),
  ...footerSections.flatMap((section) => section.links),
].map((link) => link.href);

describe("vanity redirects", () => {
  it("are never linked from the nav or footer, which link the destination instead", () => {
    expect(navAndFooterHrefs.filter((href) => VANITY_PATHS.has(href))).toEqual(
      [],
    );
  });

  it("forward internal paths to a landing page that exists", () => {
    const internalTargets = VANITY_REDIRECT_PAIRS.map(([, target]) => target)
      .filter((target) => target.startsWith("/"))
      .map(landingPage);
    expect(internalTargets.filter((page) => !existsSync(page))).toEqual([]);
  });

  it("never shadow a page of their own", () => {
    const shadowed = VANITY_REDIRECT_PAIRS.map(([source]) =>
      landingPage(source),
    ).filter(existsSync);
    expect(shadowed).toEqual([]);
  });

  it("leave the bot install routes to links shared off-site, since a prefetch of their cross-origin redirect fails CORS", () => {
    const siteHrefs = [
      ...navAndFooterHrefs,
      ...Object.values(BOT_LINKS),
      ...BOTS.flatMap((bot) =>
        [bot.primaryAction, bot.secondaryAction].map((action) => action?.href),
      ),
    ];
    expect(
      siteHrefs.filter((href) =>
        BOT_INSTALL_ROUTES.some((route) => href?.endsWith(route)),
      ),
    ).toEqual([]);
  });

  it("send /self-host to the install page", () => {
    expect(vanityTarget("/self-host")).toBe("/cli");
  });

  it("resolve a vanity path to its destination", () => {
    expect(vanityTarget("/status")).toBe("https://status.heygaia.io");
  });

  it("refuse a path that is not a vanity redirect", () => {
    expect(() => vanityTarget("/pricing")).toThrow(/not a vanity/);
  });
});
