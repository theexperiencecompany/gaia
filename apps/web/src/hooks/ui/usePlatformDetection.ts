"use client";

import { useEffect, useMemo, useState } from "react";

export type Platform =
  | "mac-arm"
  | "mac-intel"
  | "windows"
  | "linux"
  | "ios"
  | "android"
  | "unknown";

export interface PlatformInfo {
  platform: Platform;
  displayName: string;
  shortName: string;
  iconPath: string;
  downloadUrl: string | null;
  isDesktop: boolean;
  isMobile: boolean;
}

const GITHUB_RELEASES_BASE =
  "https://github.com/theexperiencecompany/gaia/releases";
const GITHUB_RELEASES_API =
  "https://api.github.com/repos/theexperiencecompany/gaia/releases?per_page=10";

// GitHub's global "latest" release tracks the web app, not desktop, so we
// resolve the newest tag starting with `desktop-` at runtime. If that fetch
// fails, buttons fall back to this filtered releases page.
const DESKTOP_RELEASES_FALLBACK = `${GITHUB_RELEASES_BASE}?q=desktop&expanded=true`;

function buildPlatformConfigs(
  tag: string | null,
): Record<Platform, Omit<PlatformInfo, "platform">> {
  const desktopUrl = (asset: string) =>
    tag
      ? `${GITHUB_RELEASES_BASE}/download/${tag}/${asset}`
      : DESKTOP_RELEASES_FALLBACK;

  return {
    "mac-arm": {
      displayName: "macOS (Apple Silicon)",
      shortName: "Mac (M-series)",
      iconPath: "/images/icons/apple.svg",
      downloadUrl: desktopUrl("GAIA-arm64.dmg"),
      isDesktop: true,
      isMobile: false,
    },
    "mac-intel": {
      displayName: "macOS (Intel)",
      shortName: "Mac (Intel)",
      iconPath: "/images/icons/apple.svg",
      downloadUrl: desktopUrl("GAIA-x64.dmg"),
      isDesktop: true,
      isMobile: false,
    },
    windows: {
      displayName: "Windows",
      shortName: "Windows",
      iconPath: "/images/icons/windows.svg",
      downloadUrl: desktopUrl("GAIA-x64.exe"),
      isDesktop: true,
      isMobile: false,
    },
    linux: {
      displayName: "Linux",
      shortName: "Linux",
      iconPath: "/images/icons/linux.svg",
      downloadUrl: desktopUrl("GAIA-x86_64.AppImage"),
      isDesktop: true,
      isMobile: false,
    },
    ios: {
      displayName: "iOS",
      shortName: "iPhone & iPad",
      iconPath: "/images/icons/apple.svg",
      downloadUrl: null, // Coming soon
      isDesktop: false,
      isMobile: true,
    },
    android: {
      displayName: "Android",
      shortName: "Android",
      iconPath: "/images/icons/google_play.svg",
      downloadUrl: null, // Coming soon
      isDesktop: false,
      isMobile: true,
    },
    unknown: {
      displayName: "Desktop",
      shortName: "Desktop",
      iconPath: "/images/icons/apple.svg",
      downloadUrl: tag
        ? `${GITHUB_RELEASES_BASE}/tag/${tag}`
        : DESKTOP_RELEASES_FALLBACK,
      isDesktop: true,
      isMobile: false,
    },
  };
}

interface GithubRelease {
  tag_name: string;
  draft: boolean;
  prerelease: boolean;
}

function useLatestDesktopTag(): string | null {
  const [tag, setTag] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(GITHUB_RELEASES_API, {
      headers: { Accept: "application/vnd.github+json" },
      signal: controller.signal,
    })
      .then((r) => (r.ok ? (r.json() as Promise<GithubRelease[]>) : null))
      .then((releases) => {
        if (!releases) return;
        const desktop = releases.find(
          (r) => r.tag_name.startsWith("desktop-") && !r.draft && !r.prerelease,
        );
        if (desktop) setTag(desktop.tag_name);
      })
      .catch(() => {});

    return () => controller.abort();
  }, []);

  return tag;
}

function detectPlatform(): Platform {
  if (typeof window === "undefined" || typeof navigator === "undefined") {
    return "unknown";
  }

  const userAgent = navigator.userAgent.toLowerCase();
  const platform = navigator.platform?.toLowerCase() || "";

  // Detect iOS
  if (/iphone|ipad|ipod/.test(userAgent)) {
    return "ios";
  }

  // Detect Android
  if (/android/.test(userAgent)) {
    return "android";
  }

  // Detect macOS
  if (platform.includes("mac") || /macintosh|mac os x/.test(userAgent)) {
    // Try to detect Apple Silicon vs Intel
    // Check for ARM architecture indicators
    const isArmMac =
      // Check if running in Rosetta or native ARM
      ((navigator as Navigator & { userAgentData?: { platform?: string } })
        .userAgentData?.platform === "macOS" &&
        // Modern detection via GPU or other hints
        /arm|aarch64/.test(userAgent)) ||
      // Check screen dimensions and device pixel ratio (M-series typically have different characteristics)
      (window.devicePixelRatio >= 2 && window.screen.width >= 1280);

    // Default to ARM for newer Macs (since 2020), but this is a best guess
    // In practice, we'll show both options on the download page
    return isArmMac ? "mac-arm" : "mac-intel";
  }

  // Detect Windows
  if (platform.includes("win") || /windows/.test(userAgent)) {
    return "windows";
  }

  // Detect Linux
  if (platform.includes("linux") || /linux/.test(userAgent)) {
    return "linux";
  }

  return "unknown";
}

export function usePlatformDetection() {
  const [platform, setPlatform] = useState<Platform>("unknown");
  const [isLoading, setIsLoading] = useState(true);
  const desktopTag = useLatestDesktopTag();

  useEffect(() => {
    setPlatform(detectPlatform());
    setIsLoading(false);
  }, []);

  const platformConfigs = useMemo(
    () => buildPlatformConfigs(desktopTag),
    [desktopTag],
  );

  const currentPlatform: PlatformInfo = {
    platform,
    ...platformConfigs[platform],
  };

  const allPlatforms: PlatformInfo[] = Object.entries(platformConfigs)
    .filter(([key]) => key !== "unknown")
    .map(([key, config]) => ({
      platform: key as Platform,
      ...config,
    }));

  const desktopPlatforms = allPlatforms.filter((p) => p.isDesktop);
  const mobilePlatforms = allPlatforms.filter((p) => p.isMobile);

  // Get platforms sorted with current platform first (for desktop)
  const sortedDesktopPlatforms = [
    ...desktopPlatforms.filter((p) => p.platform === platform),
    ...desktopPlatforms.filter((p) => p.platform !== platform),
  ];

  return {
    platform,
    platformConfigs,
    currentPlatform,
    allPlatforms,
    desktopPlatforms,
    mobilePlatforms,
    sortedDesktopPlatforms,
    isLoading,
    isMac: platform === "mac-arm" || platform === "mac-intel",
    isWindows: platform === "windows",
    isLinux: platform === "linux",
    isMobile: platform === "ios" || platform === "android",
  };
}

// Export platform configs for use in server components
export { GITHUB_RELEASES_BASE };
