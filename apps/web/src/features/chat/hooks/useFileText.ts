import { useQuery } from "@tanstack/react-query";
import { sessionFilesApi } from "@/features/chat/api/sessionFilesApi";
import type { FileViewerSource } from "@/features/chat/components/artifacts/fileViewerSource";

const FILE_TEXT_QUERY_KEY = "file-text";

interface FileText {
  text: string | null;
  loading: boolean;
  error: boolean;
}

async function fetchUrlText(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Fetching file failed with ${response.status}`);
  }
  return response.text();
}

/**
 * Fetch a file's text body for the viewer. An artifact's inline body is used
 * directly with no request; `enabled` short-circuits binary files, which
 * render from their URL instead.
 */
export function useFileText(
  source: FileViewerSource,
  enabled: boolean = true,
): FileText {
  const isArtifact = source.kind === "artifact";
  const conversationId = isArtifact ? source.conversationId : "";
  const location = isArtifact ? source.path : source.url;
  const inlineBody = isArtifact ? source.inlineBody : undefined;
  const hasInline = typeof inlineBody === "string";
  const { data, isLoading, isError } = useQuery({
    queryKey: [FILE_TEXT_QUERY_KEY, source.kind, conversationId, location],
    queryFn: () =>
      isArtifact
        ? sessionFilesApi.fetchArtifact(conversationId, location)
        : fetchUrlText(location),
    enabled: enabled && !hasInline,
    retry: false,
  });

  if (!enabled) return { text: null, loading: false, error: false };
  if (hasInline) return { text: inlineBody, loading: false, error: false };
  return { text: data ?? null, loading: isLoading, error: isError };
}
