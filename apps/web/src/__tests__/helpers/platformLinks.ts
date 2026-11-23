import type {
  GetPlatformLinksResponse,
  PlatformLinkEntry,
} from "@shared/api/generated";

/** A linked account as GET /platform-links returns it. */
export function linkedPlatform(
  platform: string,
  overrides: Partial<PlatformLinkEntry> = {},
): PlatformLinkEntry {
  return {
    platform,
    platformUserId: `${platform}-1`,
    username: null,
    displayName: null,
    connectedAt: null,
    ...overrides,
  };
}

/** The GET /platform-links body with these platforms linked. */
export function platformLinks(
  ...links: (string | PlatformLinkEntry)[]
): GetPlatformLinksResponse {
  const entries = links.map((entry) =>
    typeof entry === "string" ? linkedPlatform(entry) : entry,
  );
  return {
    platform_links: Object.fromEntries(
      entries.map((entry) => [entry.platform, entry]),
    ),
  };
}
