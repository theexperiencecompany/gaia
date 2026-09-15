import type { DesktopReleaseAsset } from "@shared/api/generated";

export type { DesktopReleaseAsset } from "@shared/api/generated";

export interface DesktopRelease {
  tag: string;
  name: string | null;
  html_url: string;
  published_at: string | null;
  assets: DesktopReleaseAsset[];
}
