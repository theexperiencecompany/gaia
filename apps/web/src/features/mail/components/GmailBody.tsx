import DOMPurify from "dompurify";
import { useLayoutEffect, useMemo, useRef } from "react";

import type { EmailData, EmailPart } from "@/types/features/mailTypes";

const decodeBase64 = (str: string): string => {
  try {
    const decoded = atob(str.replace(/-/g, "+").replace(/_/g, "/"));
    return decodeURIComponent(escape(decoded)); // Ensures proper UTF-8 decoding
  } catch (error) {
    console.error("Error decoding Base64 string:", error);
    return "";
  }
};

export default function GmailBody({ email }: { email: EmailData | null }) {
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
          ADD_TAGS: ["iframe"],
        })
      : null;
  }, [decodedHtml]);

  // Injected in a layout effect so the shadow root is populated before the
  // browser paints — no loading state needed and stale content is never shown.
  useLayoutEffect(() => {
    if (!sanitizedHtml || !shadowHostRef.current) return;

    const shadowRoot =
      shadowHostRef.current.shadowRoot ||
      shadowHostRef.current.attachShadow({ mode: "open" });
    shadowRoot.innerHTML = "";
    const contentWrapper = document.createElement("div");
    contentWrapper.innerHTML = sanitizedHtml;
    shadowRoot.appendChild(contentWrapper);
  }, [sanitizedHtml]);

  if (!email) return null;

  return (
    <div className="relative w-full overflow-auto shadow-md">
      <div ref={shadowHostRef} className="w-full bg-white p-4 text-black" />
    </div>
  );
}
