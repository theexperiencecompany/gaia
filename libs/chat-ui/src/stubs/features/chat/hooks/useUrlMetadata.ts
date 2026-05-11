/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
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

interface UseUrlMetadataResult {
  data: UrlMetadata | null;
  isLoading: boolean;
  isError: boolean;
  error: UrlMetadataError | null;
}

export const useUrlMetadata = (
  _url: string | undefined | null,
): UseUrlMetadataResult => ({
  data: null,
  isLoading: false,
  isError: false,
  error: null,
});

export const usePrefetchUrlMetadata = (): ((url: string) => void) => {
  return (_url: string) => {};
};
