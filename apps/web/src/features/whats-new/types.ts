export interface Release {
  id: string;
  title: string;
  date: string; // ISO
  summary: string; // plain text, 1-2 sentences
  html: string; // HTML body from RSS feed (rendered client-side)
  imageUrl: string | null;
  appsTouched: string[]; // ["API", "Web", "Desktop"]
  docsUrl: string;
}

export interface ReleasesResponse {
  releases: Release[];
  fetchedAt: string;
}
