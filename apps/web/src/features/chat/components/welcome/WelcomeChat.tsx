/**
 * Post-onboarding welcome experience rendered the first time a freshly
 * onboarded user lands on `/c`. Single persona-tailored bot bubble
 * (greeting + verbs + integration close) followed by two CTAs:
 * - "Connect your tools" → `/integrations` (primary / blue, integrations icon)
 * - "See what you can do" → `/use-cases` (default, circle-arrow-up-right icon)
 *
 * The seeded first message from the backend is suppressed in the post-
 * onboarding view (it already played inside the holo card reveal), so this
 * component is the only chat surface a freshly onboarded user sees here.
 */

"use client";

import { Button } from "@heroui/button";
import { CircleArrowUpRight02Icon, ConnectIcon } from "@icons";
import * as m from "motion/react-m";
import Link from "next/link";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import { BOT_BUBBLE_DEFAULTS } from "@/features/onboarding/constants/bubbleDefaults";
import { useUserStore } from "@/stores/userStore";
import { getWelcomeCopyForProfession } from "./personaCopy";

interface WelcomeChatProps {
  surface?: "chat" | "onboarding";
}

export function WelcomeChat({ surface = "chat" }: WelcomeChatProps = {}) {
  const profession = useUserStore((s) => s.onboarding?.preferences?.profession);
  const welcomeText = getWelcomeCopyForProfession(profession);

  return (
    <m.div
      className={
        surface === "onboarding"
          ? "mx-auto flex w-full max-w-3xl flex-col gap-4 pt-6 pb-32"
          : "flex w-full flex-col gap-4 pt-6 pb-32"
      }
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <ChatBubbleBot {...BOT_BUBBLE_DEFAULTS} text={welcomeText}>
        <div className="ml-10.75 mt-3 flex flex-wrap gap-2">
          <Button
            as={Link}
            href="/integrations"
            color="primary"
            endContent={<ConnectIcon className="size-4" />}
          >
            Connect your tools
          </Button>
          <Button
            as={Link}
            href="/use-cases"
            endContent={<CircleArrowUpRight02Icon className="size-4" />}
          >
            See what you can do
          </Button>
        </div>
      </ChatBubbleBot>
    </m.div>
  );
}
