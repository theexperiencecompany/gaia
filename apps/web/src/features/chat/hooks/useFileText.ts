import { useEffect, useState } from "react";
import { sessionFilesApi } from "@/features/chat/api/sessionFilesApi";
import type { FileViewerSource } from "@/features/chat/components/artifacts/fileViewerSource";

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
  const [text, setText] = useState<string | null>(
    hasInline ? inlineBody : null,
  );
  const [loading, setLoading] = useState(enabled && !hasInline);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setText(null);
      setLoading(false);
      setError(false);
      return;
    }

    if (hasInline) {
      setText(inlineBody);
      setLoading(false);
      setError(false);
      return;
    }

    let cancelled = false;
    setText(null);
    setLoading(true);
    setError(false);

    const request = isArtifact
      ? sessionFilesApi.fetchArtifact(conversationId, location)
      : fetchUrlText(location);
    request
      .then((data) => {
        if (!cancelled) setText(data);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isArtifact, conversationId, location, hasInline, inlineBody, enabled]);

  return { text, loading, error };
}
