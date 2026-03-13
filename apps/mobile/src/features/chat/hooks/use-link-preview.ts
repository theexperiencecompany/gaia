import { useQuery } from "@tanstack/react-query";
import { apiService } from "@/lib/api";
import type { LinkPreviewCardProps } from "../components/chat/link-preview-card";

const URL_REGEX =
  /https?:\/\/(www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+.~#?&/=]*)/gi;

const MAX_URLS_PER_MESSAGE = 3;

export interface LinkPreviewData extends LinkPreviewCardProps {
  url: string;
}

interface UrlMetadataResponse {
  url: string;
  title?: string;
  description?: string;
  image?: string;
  favicon?: string;
  domain?: string;
}

interface UrlMetadataBatchResponse {
  results: UrlMetadataResponse[];
}

function extractUrls(text: string): string[] {
  const matches = text.matchAll(URL_REGEX);
  const urls: string[] = [];
  for (const match of matches) {
    urls.push(match[0]);
    if (urls.length >= MAX_URLS_PER_MESSAGE) break;
  }
  return urls;
}

async function fetchUrlMetadata(urls: string[]): Promise<LinkPreviewData[]> {
  const response = await apiService.post<UrlMetadataBatchResponse>(
    "/fetch-url-metadata",
    { urls },
  );
  return (response.results ?? []).map((item) => ({
    url: item.url,
    title: item.title,
    description: item.description,
    imageUrl: item.image,
    favicon: item.favicon,
    domain: item.domain,
  }));
}

export function useLinkPreview(messageText: string) {
  const urls = extractUrls(messageText);

  return useQuery({
    queryKey: ["link-preview", ...urls],
    queryFn: () => fetchUrlMetadata(urls),
    enabled: urls.length > 0,
    staleTime: 60 * 60 * 1000,
    retry: false,
  });
}

export { extractUrls };
