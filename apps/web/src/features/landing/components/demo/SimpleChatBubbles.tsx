import Image from "next/image";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function SimpleChatBubbleBot({
  className,
  children,
  parentClassName,
  hideAvatar = false,
}: {
  children: ReactNode;
  className?: string;
  parentClassName?: string;
  hideAvatar?: boolean;
}) {
  return (
    <div className={`relative mb-3 flex items-end gap-3 ${parentClassName}`}>
      {!hideAvatar && (
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
      )}
      <div
        className={cn(
          "imessage-bubble imessage-from-them text-white",
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}
