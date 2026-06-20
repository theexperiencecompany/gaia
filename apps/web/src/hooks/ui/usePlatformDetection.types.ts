export type Platform =
  | "mac-arm"
  | "mac-intel"
  | "windows"
  | "linux"
  | "ios"
  | "android"
  | "unknown";

export type DesktopOS = "mac" | "windows" | "linux";
export type DesktopArch = "x64" | "arm64";

export interface PlatformInfo {
  platform: Platform;
  displayName: string;
  shortName: string;
  iconPath: string;
  downloadUrl: string | null;
  isDesktop: boolean;
  isMobile: boolean;
}

export interface DesktopVariant {
  os: DesktopOS;
  arch: DesktopArch;
  label: string;
  description: string;
  /** Direct asset URL, or null when this binary isn't published in the release. */
  downloadUrl: string | null;
}
