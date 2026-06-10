import { useEffect, useState } from "react";
import { sessionFilesApi } from "@/features/chat/api/sessionFilesApi";

interface ArtifactText {
  text: string | null;
  loading: boolean;
  error: boolean;
}

/**
 * Fetch the text body of an `artifacts/` artifact for inline rendering
 * (HTML/Markdown previews, the file viewer). When `inlineBody` is provided
 * by the artifact event (small + textual files), it's used directly and no
 * network request is made — keeps reload-restored previews instant.
 * `enabled` lets callers short-circuit the hook for non-textual artifacts
 * (e.g. images render via <img src=...> directly — no body fetch needed).
 */
export function useArtifactText(
  conversationId: string,
  path: string,
  inlineBody?: string,
  enabled: boolean = true,
): ArtifactText {
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

    sessionFilesApi
      .fetchArtifact(conversationId, path)
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
  }, [conversationId, path, hasInline, inlineBody, enabled]);

  return { text, loading, error };
}
