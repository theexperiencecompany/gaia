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
 * Cancels in-flight requests when the target changes or unmounts.
 */
export function useArtifactText(
  conversationId: string,
  path: string,
  inlineBody?: string,
): ArtifactText {
  const hasInline = typeof inlineBody === "string";
  const [text, setText] = useState<string | null>(
    hasInline ? inlineBody : null,
  );
  const [loading, setLoading] = useState(!hasInline);
  const [error, setError] = useState(false);

  useEffect(() => {
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
  }, [conversationId, path, hasInline, inlineBody]);

  return { text, loading, error };
}
