import Image from "next/image";
import { type ReactNode, useId } from "react";

import { splitMessageByBreaks } from "@/features/chat/utils/messageBreakUtils";
import { cn } from "@/lib/utils";

export function SimpleChatBubbleBot({
  className,
  children,
  parentClassName,
}: {
  children: ReactNode;
  className?: string;
  parentClassName?: string;
}) {
  const baseId = useId();
  // Handle NEW_MESSAGE_BREAK for multiple bubbles with single avatar
  const childrenString = typeof children === "string" ? children : "";
  const bubbles = childrenString
    ? splitMessageByBreaks(childrenString)
    : [children];
  const hasMultipleBubbles = bubbles.length > 1;

  return (
    <div className={`relative mb-3 flex items-end gap-3 ${parentClassName}`}>
      <div className="relative z-[1] w-[35px]">
        <Image
          src="/images/logos/logo.webp"
          width={50}
          height={50}
          loading="lazy"
          alt="GAIA"
          className="rounded-full"
        />
      </div>
      {hasMultipleBubbles ? (
        <div className="flex flex-col gap-1">
          {bubbles.map((bubble, index) => {
            const isFirst = index === 0;
            const isLast = index === bubbles.length - 1;
            const groupedClasses = isFirst
              ? "imessage-grouped-first"
              : isLast
                ? "imessage-grouped-last"
                : "imessage-grouped-middle";

            return (
              <div
                // biome-ignore lint/suspicious/noArrayIndexKey: doesn't change so it's fine
                key={`${baseId}-bubble-${index}`}
                className={cn(
                  "chat_bubble imessage-bubble imessage-from-them text-white",
                  groupedClasses,
                  className,
                )}
              >
                {bubble}
              </div>
            );
          })}
        </div>
      ) : (
        <div
          className={cn(
            "chat_bubble imessage-bubble imessage-from-them text-white",
            className,
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}
