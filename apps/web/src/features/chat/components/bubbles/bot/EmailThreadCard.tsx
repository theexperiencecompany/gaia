import { Accordion, Chip, ScrollShadow } from "@heroui/react";
import { useCallback } from "react";
import { accordionVariants } from "@/components/shared/accordionVariants";

import { Gmail } from "@/components/shared/icons";
import { sanitizeEmailHtml } from "@/features/mail/utils/sanitizeEmailHtml";
import type { EmailThreadData } from "@/types/features/mailTypes";
import { parseEmail } from "../../../../mail/utils/mailUtils";

const accordionStyles = accordionVariants({ variant: "light" });

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
  const htmlContent = content?.html || content?.text || body;

  const sanitizedHtml = sanitizeEmailHtml(htmlContent);

  // Injects sanitized email into a shadow root via a ref callback — React
  // re-runs it synchronously at commit when its identity changes
  // (sanitizedHtml changes), skipping a render/effect/setState flash.
  const attachShadowContent = useCallback(
    (host: HTMLDivElement | null) => {
      if (!host) return;
      const shadowRoot = host.shadowRoot || host.attachShadow({ mode: "open" });
      shadowRoot.innerHTML = "";
      const contentWrapper = document.createElement("div");
      contentWrapper.innerHTML = sanitizedHtml;
      shadowRoot.appendChild(contentWrapper);
    },
    [sanitizedHtml],
  );

  if (!body && (!content || (!content.text && !content.html))) {
    return (
      <div className="p-4 text-sm text-gray-500">No content available.</div>
    );
  }

  return (
    <div className="relative w-full overflow-auto shadow-md">
      <div
        ref={attachShadowContent}
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
      className={`mx-auto w-full rounded-2xl bg-zinc-800 p-3 py-0 text-white transition-colors duration-300`}
    >
      <Accordion
        className={accordionStyles.base()}
        defaultExpandedKeys={["email-thread"]}
      >
        <Accordion.Item id="email-thread">
          <Accordion.Heading>
            <Accordion.Trigger className={accordionStyles.trigger()}>
              <div className="flex items-center gap-3">
                <Gmail width={22} height={22} />
                <div className="flex flex-col">
                  <span className="text-sm font-medium">
                    Fetched Email Thread
                  </span>
                </div>
              </div>
              <Accordion.Indicator className={accordionStyles.indicator()} />
            </Accordion.Trigger>
          </Accordion.Heading>
          <Accordion.Panel className={accordionStyles.panel()}>
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
                              <Chip variant="soft" size="sm">
                                From
                              </Chip>
                            </div>
                            <span className="text-sm text-zinc-300">
                              {senderName}
                            </span>
                            <span className="text-xs font-light text-zinc-500">
                              {senderEmail}
                            </span>
                          </div>
                          <span className="text-xs text-zinc-400">
                            {formatTime(message.time)}
                          </span>
                        </div>
                        <div className="flex flex-row items-center gap-2">
                          <div className="w-15">
                            <Chip variant="soft" size="sm">
                              Subject
                            </Chip>
                          </div>
                          <div className="text-sm font-medium text-zinc-300">
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
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </div>
  );
}
