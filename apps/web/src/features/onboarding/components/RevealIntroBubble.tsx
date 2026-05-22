/**
 * Standard "intro bot bubble + reveal content" wrapper used by the
 * writing-style and todos reveals. Both stages opened with the same
 * fade-up `m.div` containing a ChatBubbleBot intro plus children.
 */

"use client";

import * as m from "motion/react-m";
import type { ReactNode } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import { BOT_BUBBLE_DEFAULTS } from "../constants/bubbleDefaults";
import { MOTION_FADE_UP } from "../constants/motion";

interface RevealIntroBubbleProps {
  text: string;
  children?: ReactNode;
}

export function RevealIntroBubble({ text, children }: RevealIntroBubbleProps) {
  return (
    <m.div className="space-y-3" {...MOTION_FADE_UP}>
      <ChatBubbleBot {...BOT_BUBBLE_DEFAULTS} text={text} />
      {children}
    </m.div>
  );
}
