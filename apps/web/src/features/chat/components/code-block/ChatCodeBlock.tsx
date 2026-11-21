"use client";

import type { ComponentProps } from "react";
import { useActiveLiveLoading } from "@/features/chat/live/useLiveChat";
import CodeBlock from "./CodeBlock";

/** CodeBlock inside a chat message, tracking whether the active turn is still streaming. */
export const ChatCodeBlock = (
  props: Omit<ComponentProps<typeof CodeBlock>, "isStreaming">,
) => {
  const { isLoading } = useActiveLiveLoading();
  return <CodeBlock {...props} isStreaming={isLoading} />;
};
