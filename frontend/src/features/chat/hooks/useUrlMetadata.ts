import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

interface UrlMetadata {
  title: string | null;
  description: string | null;
  favicon: string | null;
  website_name: string | null;
  website_image: string | null;
  url: string;
}

interface UrlMetadataError {
  message: string;
  code?: number;
}

const isEmail = (str: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(str);

const isValidHttpUrl = (str: string): boolean => {
  try {
    const url = new URL(str);
    return /^(http|https):$/.test(url.protocol);
  } catch {
    return false;
  }
};

// Global batch manager for automatic request batching
const pendingBatch = new Set<string>();
const batchResolvers = new Map<
  string,
  {
    resolve: (data: UrlMetadata) => void;
    reject: (error: Error) => void;
  }
>();
let batchTimeout: NodeJS.Timeout | null = null;

const processBatch = async () => {
  const urls = Array.from(pendingBatch);
  const resolvers = new Map(batchResolvers);

  // Clear current batch
  pendingBatch.clear();
  batchResolvers.clear();
  batchTimeout = null;

  if (urls.length === 0) return;

  try {
    // Single API call for all URLs
    const response = await api.post("/fetch-url-metadata", { urls });

    // Resolve individual promises with their data
    urls.forEach((url) => {
      const resolver = resolvers.get(url);
      const metadata = response.data.results[url];

      if (resolver) {
        if (metadata) {
          resolver.resolve(metadata);
        } else {
          resolver.reject(new Error(`No metadata found for ${url}`));
        }
      }
    });
  } catch (error) {
    // Reject all pending resolvers on batch failure
    resolvers.forEach((resolver) => {
      resolver.reject(error as Error);
    });
  }
};

const batchUrlRequest = (url: string): Promise<UrlMetadata> => {
  return new Promise((resolve, reject) => {
    // Add to batch
    pendingBatch.add(url);
    batchResolvers.set(url, { resolve, reject });

    // Debounce batch request (1 second window to collect multiple URLs)
    if (batchTimeout) clearTimeout(batchTimeout);
    batchTimeout = setTimeout(processBatch, 1000);
  });
};

/**
 * Custom hook to fetch URL metadata with React Query optimization
 * Features:
 * - Automatic caching with 5-minute stale time
 * - Deduplication of identical requests
 * - Background refetching for fresh data
 * - Error handling with retry logic
 * - Conditional fetching based on URL validity
 */
export const useUrlMetadata = (url: string | undefined | null) => {
  const isValidUrl =
    url && isValidHttpUrl(url) && !isEmail(url) && !url.startsWith("mailto:");

  const result = useQuery<UrlMetadata, UrlMetadataError>({
    queryKey: ["url-metadata", url],
    queryFn: async () => {
      if (!url) {
        throw new Error("URL is required");
      }

      // Use batched request - automatically groups URLs that are requested within 100ms
      return await batchUrlRequest(url);
    },
    staleTime: 5 * 60 * 1000, // 5 minutes - metadata rarely changes
    gcTime: 30 * 60 * 1000, // 30 minutes - keep in cache for longer
    retry: (failureCount, error) => {
      if (
        error &&
        "code" in error &&
        error.code &&
        error.code >= 400 &&
        error.code < 500
      ) {
        return false;
      }
      return failureCount < 2;
    },
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 5000),
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: "always",
  });

  // Return early state for invalid URLs, but after calling useQuery
  if (!isValidUrl) {
    return { data: null, isLoading: false, isError: false, error: null };
  }

  return result;
};

/**
 * Hook to prefetch URL metadata for better UX
 * Useful for prefetching when user hovers over links
 */
export const usePrefetchUrlMetadata = () => {
  const queryClient = useQueryClient();

  return (url: string) => {
    const isValidUrl =
      url && isValidHttpUrl(url) && !isEmail(url) && !url.startsWith("mailto:");

    if (!isValidUrl) return;

    queryClient.prefetchQuery({
      queryKey: ["url-metadata", url],
      queryFn: async () => {
        return await batchUrlRequest(url);
      },
      staleTime: 30 * 24 * 60 * 60 * 1000, // 1 month
    });
  };
};
