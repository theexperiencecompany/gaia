"use client";

import { useEffect, useMemo, useState } from "react";
import { desktopApi } from "@/features/download/api/desktopApi";
import type { DesktopRelease } from "@/features/download/types";
import type {
  DesktopArch,
  DesktopOS,
  DesktopVariant,
  Platform,
  PlatformInfo,
} from "./usePlatformDetection.types";

export type {
  DesktopArch,
  DesktopOS,
  DesktopVariant,
  Platform,
  PlatformInfo,
} from "./usePlatformDetection.types";

const GITHUB_RELEASES_BASE =
  "https://github.com/theexperiencecompany/gaia/releases";

// Expected asset filename per (OS, arch). Mirrors apps/desktop/electron-builder.yml
// `artifactName: "${productName}-${arch}.${ext}"`. Linux x64 ships as the x86_64
// AppImage. Download URLs are resolved by matching these names against the real
// published assets, so a missing binary (e.g. Windows arm64, not yet built)
// resolves to null and is simply not offered — never a 404.
const DESKTOP_ASSET_NAMES: Record<DesktopOS, Record<DesktopArch, string>> = {
  mac: { x64: "GAIA-x64.dmg", arm64: "GAIA-arm64.dmg" },
  windows: { x64: "GAIA-x64.exe", arm64: "GAIA-arm64.exe" },
  linux: { x64: "GAIA-x86_64.AppImage", arm64: "GAIA-arm64.AppImage" },
};

const DESKTOP_VARIANT_META: Record<
  DesktopOS,
  Record<DesktopArch, { label: string; description: string }>
> = {
  mac: {
    x64: { label: "Intel", description: "For Macs with an Intel processor" },
    arm64: {
      label: "Apple Silicon",
      description: "For Macs with M1, M2, M3, or M4 chips",
    },
  },
  windows: {
    x64: { label: "x64", description: "For 64-bit Intel or AMD processors" },
    arm64: { label: "ARM64", description: "For Windows on ARM devices" },
  },
  linux: {
    x64: { label: "x64", description: "For 64-bit Intel or AMD processors" },
    arm64: { label: "ARM64", description: "For 64-bit ARM processors" },
  },
};

const DESKTOP_OS_ORDER: DesktopArch[] = ["x64", "arm64"];

function resolveAssetUrl(
  release: DesktopRelease | null,
  assetName: string,
): string | null {
  if (!release) return null;
  return (
    release.assets.find((asset) => asset.name === assetName)?.download_url ??
    null
  );
}

function buildDesktopDownloads(
  release: DesktopRelease | null,
): Record<DesktopOS, DesktopVariant[]> {
  const forOs = (os: DesktopOS): DesktopVariant[] =>
    DESKTOP_OS_ORDER.map((arch) => ({
      os,
      arch,
      label: DESKTOP_VARIANT_META[os][arch].label,
      description: DESKTOP_VARIANT_META[os][arch].description,
      downloadUrl: resolveAssetUrl(release, DESKTOP_ASSET_NAMES[os][arch]),
    }));

  return {
    mac: forOs("mac"),
    windows: forOs("windows"),
    linux: forOs("linux"),
  };
}

// Legacy PlatformInfo map kept for consumers that key off a single Platform
// (e.g. the settings download submenu). Mac keeps its two arch entries; Windows
// and Linux expose their x64 build as the default single-click download.
function buildPlatformConfigs(
  downloads: Record<DesktopOS, DesktopVariant[]>,
): Record<Platform, Omit<PlatformInfo, "platform">> {
  const url = (os: DesktopOS, arch: DesktopArch): string | null =>
    downloads[os].find((v) => v.arch === arch)?.downloadUrl ?? null;

  return {
    "mac-arm": {
      displayName: "macOS (Apple Silicon)",
      shortName: "Mac (M-series)",
      iconPath: "/images/icons/apple.svg",
      downloadUrl: url("mac", "arm64"),
      isDesktop: true,
      isMobile: false,
    },
    "mac-intel": {
      displayName: "macOS (Intel)",
      shortName: "Mac (Intel)",
      iconPath: "/images/icons/apple.svg",
      downloadUrl: url("mac", "x64"),
      isDesktop: true,
      isMobile: false,
    },
    windows: {
      displayName: "Windows",
      shortName: "Windows",
      iconPath: "/images/icons/windows.svg",
      downloadUrl: url("windows", "x64"),
      isDesktop: true,
      isMobile: false,
    },
    linux: {
      displayName: "Linux",
      shortName: "Linux",
      iconPath: "/images/icons/linux.svg",
      downloadUrl: url("linux", "x64"),
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
      downloadUrl: null,
      isDesktop: true,
      isMobile: false,
    },
  };
}

function detectedDesktopOf(
  platform: Platform,
): { os: DesktopOS; arch: DesktopArch } | null {
  switch (platform) {
    case "mac-arm":
      return { os: "mac", arch: "arm64" };
    case "mac-intel":
      return { os: "mac", arch: "x64" };
    case "windows":
      return { os: "windows", arch: "x64" };
    case "linux":
      return { os: "linux", arch: "x64" };
    default:
      return null;
  }
}

function useLatestDesktopRelease(): {
  release: DesktopRelease | null;
  isLoading: boolean;
} {
  const [release, setRelease] = useState<DesktopRelease | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let active = true;
    desktopApi
      .getLatestRelease()
      .then((data) => {
        if (active) setRelease(data);
      })
      .catch((error) => {
        // Degrade gracefully: buttons fall back to the GitHub releases page.
        // Logged (console.error survives prod stripping) so an outage is visible.
        console.error("Failed to resolve latest desktop release", error);
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return { release, isLoading };
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
  const { release, isLoading: isDesktopReleaseLoading } =
    useLatestDesktopRelease();

  useEffect(() => {
    setPlatform(detectPlatform());
    setIsLoading(false);
  }, []);

  const desktopDownloads = useMemo(
    () => buildDesktopDownloads(release),
    [release],
  );
  const platformConfigs = useMemo(
    () => buildPlatformConfigs(desktopDownloads),
    [desktopDownloads],
  );

  const currentPlatform: PlatformInfo = {
    platform,
    ...platformConfigs[platform],
  };

  const desktopPlatforms: PlatformInfo[] = Object.entries(platformConfigs)
    .filter(([key]) => key !== "unknown")
    .map(([key, config]) => ({ platform: key as Platform, ...config }))
    .filter((p) => p.isDesktop);

  return {
    platform,
    currentPlatform,
    desktopPlatforms,
    desktopDownloads,
    detectedDesktop: detectedDesktopOf(platform),
    isLoading,
    isDesktopReleaseLoading,
  };
}

// Exposed for the download page's SEO schema and the "All releases" link.
export { GITHUB_RELEASES_BASE };
