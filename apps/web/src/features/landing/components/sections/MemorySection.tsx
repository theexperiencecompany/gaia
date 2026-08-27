"use client";

import { Brain02Icon, ConnectIcon, PencilEdit02Icon } from "@icons";
import { useInView } from "motion/react";
import { useRef } from "react";
import { ChatDemo, type ChatMessageItem } from "../iphone/ChatDemo";
import { SplitShowcase } from "./SplitShowcase";

const MESSAGES: ChatMessageItem[] = [
  { divider: "Jan 14" },
  {
    from: "me",
    text: "btw my sister's birthday is march 3, she's obsessed with pottery lately",
    status: "read",
  },
  {
    from: "them",
    text: "noted 🫡",
  },
  { divider: "Mar 1" },
  {
    from: "them",
    text: "your sister's birthday is in 2 days 🎁 I found a hand-thrown pottery kit that arrives tomorrow. want me to order it?",
  },
  {
    from: "me",
    text: "you're the best. yes",
    status: "read",
  },
];

export default function MemorySection() {
  const tileRef = useRef<HTMLDivElement>(null);
  const inView = useInView(tileRef, { once: true, amount: 0.45 });
  return (
    <SplitShowcase
      title="It remembers, so you don't"
      subtitle="Say something once and GAIA files it away, then acts on it at exactly the right moment, even weeks later."
      rows={[
        {
          icon: <Brain02Icon width={18} height={18} />,
          label: "Learns your people, preferences, and patterns",
        },
        {
          icon: <ConnectIcon width={18} height={18} />,
          label: "Acts on what you said weeks ago, unprompted",
        },
        {
          icon: <PencilEdit02Icon width={18} height={18} />,
          label: "Every memory is visible, editable, and yours to delete",
        },
      ]}
    >
      <div ref={tileRef} className="absolute inset-0">
        <ChatDemo
          platform="telegram"
          title="GAIA"
          subtitle="bot"
          messages={MESSAGES}
          composerPlaceholder="Message on Telegram"
          play={inView}
          className="absolute inset-0"
        />
      </div>
    </SplitShowcase>
  );
}
