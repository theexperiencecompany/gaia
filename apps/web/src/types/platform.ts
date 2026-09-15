import type { GetPlatformLinksResponse } from "@shared/api/generated";

/** The map `GET /platform-links` returns: platform id to its link. */
export type PlatformLinks = GetPlatformLinksResponse["platform_links"];
