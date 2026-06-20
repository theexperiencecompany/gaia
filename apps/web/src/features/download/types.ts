export interface DesktopReleaseAsset {
  name: string;
  download_url: string;
  size: number;
  content_type: string | null;
}

export interface DesktopRelease {
  tag: string;
  name: string | null;
  html_url: string;
  published_at: string | null;
  assets: DesktopReleaseAsset[];
}
