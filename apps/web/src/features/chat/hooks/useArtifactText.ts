import { useEffect, useState } from "react";
import { sessionFilesApi } from "@/features/chat/api/sessionFilesApi";

interface ArtifactText {
  text: string | null;
  loading: boolean;
  error: boolean;
}

/**
 * Fetch the text body of an `artifacts/` artifact for inline rendering
 * (HTML/Markdown previews, the file viewer). Cancels in-flight requests when
 * the target changes or the component unmounts.
 */
export function useArtifactText(
  conversationId: string,
  path: string,
): ArtifactText {
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
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
  }, [conversationId, path]);

  return { text, loading, error };
}
