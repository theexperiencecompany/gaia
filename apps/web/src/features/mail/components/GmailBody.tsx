import DOMPurify from "dompurify";
import { useEffect, useMemo, useRef, useState } from "react";

import Spinner from "@/components/ui/spinner";
import type { EmailData, EmailPart } from "@/types/features/mailTypes";

export const decodeBase64 = (str: string): string => {
  try {
    const decoded = atob(str.replace(/-/g, "+").replace(/_/g, "/"));
    const bytes = Uint8Array.from(decoded, (c) => c.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  } catch (error) {
    console.error("Error decoding Base64 string:", error);
    return "";
  }
};

export default function GmailBody({ email }: { email: EmailData | null }) {
  const [loading, setLoading] = useState(true);
  const shadowHostRef = useRef<HTMLDivElement | null>(null);

  const decodedHtml = useMemo(() => {
    if (!email) return null;

    const htmlPart = email.payload.parts?.find(
      (p: EmailPart) => p.mimeType === "text/html",
    )?.body?.data;

    if (htmlPart) return decodeBase64(htmlPart);
    if (email.payload.body?.data) return decodeBase64(email.payload.body.data);
    return null;
  }, [email]);

  const sanitizedHtml = useMemo(() => {
    return decodedHtml
      ? DOMPurify.sanitize(decodedHtml, {
          ADD_ATTR: ["target"],
        })
      : null;
  }, [decodedHtml]);

  useEffect(() => {
    if (!sanitizedHtml) {
      setLoading(false);
      return;
    }

    const host = shadowHostRef.current;
    if (!host) return;

    const shadowRoot =
      host.shadowRoot || host.attachShadow({ mode: "open" });
    shadowRoot.innerHTML = "";
    const contentWrapper = document.createElement("div");
    contentWrapper.innerHTML = sanitizedHtml;
    shadowRoot.appendChild(contentWrapper);
    setLoading(false);

    return () => {
      shadowRoot.innerHTML = "";
    };
  }, [sanitizedHtml]);

  if (!email) return null;

  return (
    <div className="relative w-full overflow-auto shadow-md">
      {loading && (
        <div className="absolute inset-0 z-10 flex h-full w-full items-start justify-center bg-black/90 p-10 backdrop-blur-3xl">
          <Spinner />
        </div>
      )}
      <div ref={shadowHostRef} className="w-full bg-white p-4 text-black" />
    </div>
  );
}
