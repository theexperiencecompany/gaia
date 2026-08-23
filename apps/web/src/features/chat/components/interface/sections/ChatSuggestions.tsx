import { Button } from "@heroui/button";
import * as m from "motion/react-m";
import type React from "react";
import { useEffect, useState } from "react";
import {
  pickStarterPrompts,
  type StarterPrompt,
} from "@/features/chat/components/interface/sections/starterPrompts";
import { useAppendToInput } from "@/stores/composerStore";
import { useUserStore } from "@/stores/userStore";

export const ChatSuggestions: React.FC = () => {
  const profession = useUserStore((s) => s.onboarding?.preferences?.profession);
  const appendToInput = useAppendToInput();
  // Picked post-mount: Math.random during render made server and client
  // disagree on every load (hydration mismatch → discarded server tree).
  const [prompts, setPrompts] = useState<StarterPrompt[]>([]);

  useEffect(() => {
    setPrompts(pickStarterPrompts(profession));
  }, [profession]);

  if (prompts.length === 0) return null;

  return (
    <section className="mt-8 w-full max-w-lg" aria-label="Suggested tasks">
      <m.div
        initial="hidden"
        animate="visible"
        variants={{
          visible: {
            transition: {
              staggerChildren: 0.05,
            },
          },
        }}
        className="flex flex-col gap-1"
      >
        {prompts.map(({ prompt, icon: Icon }) => (
          <m.div
            key={prompt}
            variants={{
              hidden: { opacity: 0, y: 8 },
              visible: { opacity: 1, y: 0 },
            }}
          >
            <Button
              fullWidth
              variant="light"
              size="sm"
              onPress={() => appendToInput(prompt)}
              className="h-10 justify-start gap-3 rounded-xl px-3 text-sm font-normal text-zinc-400 hover:text-zinc-100"
              startContent={
                <Icon size={18} className="shrink-0 text-zinc-500" />
              }
            >
              {prompt}
            </Button>
          </m.div>
        ))}
      </m.div>
    </section>
  );
};

ChatSuggestions.displayName = "ChatSuggestions";
