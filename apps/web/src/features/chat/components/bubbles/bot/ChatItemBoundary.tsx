import { Alert01Icon } from "@icons";
import type { ReactNode } from "react";
import ErrorBoundary from "@/components/shared/ErrorBoundary";
import { streamLogError } from "@/lib/streamLogger";

interface ChatItemBoundaryProps {
  children: ReactNode;
  /** What this guards (a tool name, "text", "message"); tags the report. */
  item: string;
  /** The item's data: a new value retries the render, so a later frame can recover. */
  resetKey: unknown;
  messageId?: string;
}

/**
 * Contains a render crash to one chat item. Without it a single bad card
 * unwinds to the route error boundary and blanks the whole conversation.
 */
export function ChatItemBoundary({
  children,
  item,
  resetKey,
  messageId,
}: ChatItemBoundaryProps) {
  return (
    <ErrorBoundary
      scope={`chat:${item}`}
      resetKey={resetKey}
      onError={(error) =>
        streamLogError("render", `${item}:crashed`, {
          detail: { messageId, message: error.message },
        })
      }
      fallback={
        <div
          className="flex items-center gap-2 py-1 text-zinc-400"
          role="alert"
        >
          <Alert01Icon className="shrink-0" height={15} width={15} />
          <span className="text-xs">This part couldn't be displayed</span>
        </div>
      }
    >
      {children}
    </ErrorBoundary>
  );
}
