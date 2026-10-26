"use client";

import type { ComponentProps } from "react";
import { useActiveLoading } from "@/stores/streamStore";
import CodeBlock from "./CodeBlock";

/** CodeBlock inside a chat message, tracking whether the active turn is still streaming. */
const ChatCodeBlock = (
  props: Omit<ComponentProps<typeof CodeBlock>, "isStreaming">,
) => {
  const { isLoading } = useActiveLoading();
  return <CodeBlock {...props} isStreaming={isLoading} />;
};

export default ChatCodeBlock;
