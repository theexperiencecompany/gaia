import { Accordion, AccordionItem } from "@heroui/accordion";
import { Chip } from "@heroui/chip";
import { ScrollShadow } from "@heroui/scroll-shadow";
import DOMPurify from "dompurify";
import { useEffect, useRef, useState } from "react";

import { Gmail } from "@/components";
import type { EmailThreadData } from "@/types/features/mailTypes";

import { parseEmail } from "../../../../mail/utils/mailUtils";

// Use the same formatTime function as EmailListCard
function formatTime(time: string | null): string {
  if (!time) return "Yesterday";

  const date = new Date(time);
  const now = new Date();
  const diffInHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);

  if (diffInHours < 24) {
    return date.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } else if (diffInHours < 48) {
    return "Yesterday";
  } else {
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  }
}

function EmailBodyRenderer({
  body,
  content,
}: {
  body: string;
  content?: { text: string; html: string };
}) {
  const [loading, setLoading] = useState(true);
  const shadowHostRef = useRef<HTMLDivElement | null>(null);

  const htmlContent = content?.html || content?.text || body;

  const sanitizedHtml = DOMPurify.sanitize(htmlContent, {
    ADD_ATTR: ["target"],
    ADD_TAGS: ["iframe"],
  });

  useEffect(() => {
    if (!sanitizedHtml) {
      setLoading(false);
      return;
    }

    if (shadowHostRef.current) {
      const shadowRoot =
        shadowHostRef.current.shadowRoot ||
        shadowHostRef.current.attachShadow({ mode: "open" });
      shadowRoot.innerHTML = "";
      const contentWrapper = document.createElement("div");
      contentWrapper.innerHTML = sanitizedHtml;
      shadowRoot.appendChild(contentWrapper);
      setLoading(false);
    }
  }, [sanitizedHtml]);

  if (!body && (!content || (!content.text && !content.html))) {
    return (
      <div className="p-4 text-sm text-gray-500">No content available.</div>
    );
  }

  return (
    <div className="relative w-full overflow-auto shadow-md">
      {loading && (
        <div className="absolute inset-0 z-10 flex h-full w-full items-start justify-center bg-surface-50/90 p-10 backdrop-blur-3xl">
          <div className="h-6 w-6 animate-spin rounded-full border-b-2 border-white"></div>
        </div>
      )}
      <div
        ref={shadowHostRef}
        className="w-full rounded-lg bg-white p-4 text-black"
      />
    </div>
  );
}

export default function EmailThreadCard({
  emailThreadData,
}: {
  emailThreadData: EmailThreadData;
}) {
  return (
    <div
      className={`mx-auto w-full rounded-2xl bg-surface-200 p-3 py-0 text-white transition-all duration-300`}
    >
      <Accordion variant="light" defaultExpandedKeys={["email-thread"]}>
        <AccordionItem
          key="email-thread"
          aria-label="Email Thread"
          title={
            <div className="flex items-center gap-3">
              <Gmail width={22} height={22} />
              <div className="flex flex-col">
                <span className="text-sm font-medium">
                  Fetched Email Thread
                </span>
              </div>
            </div>
          }
        >
          <ScrollShadow className="max-h-[50vh]">
            <div className="space-y-3">
              {emailThreadData.messages.map((message) => {
                const { name: senderName, email: senderEmail } = parseEmail(
                  message.from,
                );

                return (
                  <div key={message.id} className="pt-0 pb-2">
                    <div className="mb-4 flex w-full flex-col items-start justify-start gap-1">
                      <div className="flex w-full flex-row items-center justify-between">
                        <div className="flex flex-row items-center gap-2">
                          <div className="w-15">
                            <Chip variant="flat" size="sm" radius="sm">
                              From
                            </Chip>
                          </div>
                          <span className="text-sm text-foreground-600">
                            {senderName}
                          </span>
                          <span className="text-xs font-light text-foreground-400">
                            {senderEmail}
                          </span>
                        </div>
                        <span className="text-xs text-foreground-500">
                          {formatTime(message.time)}
                        </span>
                      </div>
                      <div className="flex flex-row items-center gap-2">
                        <div className="w-15">
                          <Chip variant="flat" size="sm" radius="sm">
                            Subject
                          </Chip>
                        </div>
                        <div className="text-sm font-medium text-foreground-600">
                          {message.subject}
                        </div>
                      </div>
                    </div>
                    {message.body && (
                      <div className="mt-3">
                        <EmailBodyRenderer
                          body={message.body}
                          content={message.content}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </ScrollShadow>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
