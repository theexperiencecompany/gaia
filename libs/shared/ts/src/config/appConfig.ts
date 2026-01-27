/**
 * GAIA Application Configuration
 * Shared configuration for all GAIA applications (web, bots, mobile).
 */

export const appConfig = {
  site: {
    name: "GAIA",
    copyright: "Copyright © 2025 The Experience Company. All rights reserved.",
    domain: "heygaia.io",
    webUrl: process.env.GAIA_WEB_URL || "https://heygaia.io",
  },
} as const;
