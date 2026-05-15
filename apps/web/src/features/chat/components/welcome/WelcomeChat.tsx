/**
 * Post-onboarding welcome experience rendered the first time a freshly
 * onboarded user lands on `/c`. Single persona-tailored bot bubble
 * (greeting + verbs + integration close) followed by two CTAs:
 * - "Connect your tools" → `/integrations` (primary / blue)
 * - "Browse the playbook" → `/marketplace` (default)
 *
 * The seeded first message from the backend renders separately above this
 * — this component owns only the welcome follow-up + buttons.
 */

"use client";

import { Button } from "@heroui/button";
import * as m from "motion/react-m";
import { useRouter } from "next/navigation";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import { BOT_BUBBLE_DEFAULTS } from "@/features/onboarding/constants/bubbleDefaults";
import { useUserStore } from "@/stores/userStore";
import { getWelcomeCopyForProfession } from "./personaCopy";

interface WelcomeChatProps {
  surface?: "chat" | "onboarding";
}

export function WelcomeChat({ surface = "chat" }: WelcomeChatProps = {}) {
  const router = useRouter();
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
          <Button color="primary" onPress={() => router.push("/integrations")}>
            Connect your tools
          </Button>
          <Button onPress={() => router.push("/marketplace")}>
            Browse the playbook
          </Button>
        </div>
      </ChatBubbleBot>
    </m.div>
  );
}
