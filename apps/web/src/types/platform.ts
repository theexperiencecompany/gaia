import type { Schema } from "@shared/api/generated";

/** One linked messaging account, as `GET /platform-links` returns it. */
export type PlatformLink = Schema<"PlatformLinkEntry">;

/** The map `GET /platform-links` returns: platform id to its link. */
export type PlatformLinks =
  Schema<"GetPlatformLinksResponse">["platform_links"];
