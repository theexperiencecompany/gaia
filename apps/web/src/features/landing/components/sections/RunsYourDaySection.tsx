"use client";

import { AlarmClockIcon, CheckmarkCircle02Icon, TaskDailyIcon } from "@icons";
import { useInView } from "motion/react";
import { useRef } from "react";
import { ChatDemo, type ChatMessageItem } from "../iphone/ChatDemo";
import { SplitShowcase } from "./SplitShowcase";

const MESSAGES: ChatMessageItem[] = [
  { divider: "7:02 AM" },
  {
    from: "them",
    text: "morning ☀️ 4 back-to-backs from 9:30, and the investor update is due at 5",
    time: "7:02",
  },
  {
    from: "them",
    text: "want me to clear everything else off your plate?",
    time: "7:02",
  },
  {
    from: "me",
    text: "yes pls 🙏",
    time: "7:04",
    status: "read",
  },
  {
    from: "them",
    text: "done. standup moved to 11, the $4,200 invoice chased, 3 replies drafted for your approval",
    time: "7:29",
  },
  { divider: "6:14 PM" },
  {
    from: "them",
    text: "evening wrap: 9 tasks done, 1 needs you. that's 3 hours back today 🌙",
    time: "6:14",
  },
];

export default function RunsYourDaySection() {
  const tileRef = useRef<HTMLDivElement>(null);
  const inView = useInView(tileRef, { once: true, amount: 0.45 });
  return (
    <SplitShowcase
      title="Your day runs itself"
      subtitle="One briefing in the morning, one tap to approve. GAIA works through your inbox, calendar, and tasks while you do the real work."
      rows={[
        {
          icon: <AlarmClockIcon width={18} height={18} />,
          label: "Wakes you with a briefing and the day already planned",
        },
        {
          icon: <CheckmarkCircle02Icon width={18} height={18} />,
          label: "Drafts replies, moves meetings, and chases follow-ups",
        },
        {
          icon: <TaskDailyIcon width={18} height={18} />,
          label: "Reports back with what got done and what needs you",
        },
      ]}
    >
      <div ref={tileRef} className="absolute inset-0">
        <ChatDemo
          platform="whatsapp"
          title="GAIA"
          messages={MESSAGES}
          composerPlaceholder="Message on WhatsApp"
          play={inView}
          className="absolute inset-0"
        />
      </div>
    </SplitShowcase>
  );
}
