import type { Schema } from "@shared/api/generated";
export type DesktopReleaseAsset = Schema<"DesktopReleaseAsset">;

export interface DesktopRelease {
  tag: string;
  name: string | null;
  html_url: string;
  published_at: string | null;
  assets: DesktopReleaseAsset[];
}
