"use client";

import { Button } from "@heroui/button";
import { ArrowRight02Icon, SparklesIcon } from "@icons";
import * as m from "motion/react-m";
import { useRouter } from "next/navigation";
import { useAppendToInput } from "@/stores/composerStore";
import { CARD_TRANSITION, CARD_VARIANTS, ITEM_VARIANTS } from "./doneMotion";
import type { StarterPrompt } from "./starterPrompts";

interface StarterPromptsCardProps {
  prompts: StarterPrompt[];
}

export function StarterPromptsCard({ prompts }: StarterPromptsCardProps) {
  const router = useRouter();
  const appendToInput = useAppendToInput();

  return (
    <m.div
      variants={CARD_VARIANTS}
      transition={CARD_TRANSITION}
      className="w-full rounded-2xl bg-zinc-800 p-4"
    >
      <div className="mb-3 flex items-center gap-2">
        <SparklesIcon size={14} className="text-zinc-500" />
        <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
          Try one to get started
        </p>
      </div>
      <m.div
        initial="hidden"
        animate="visible"
        variants={{
          hidden: {},
          visible: {
            transition: { staggerChildren: 0.06, delayChildren: 0.1 },
          },
        }}
        className="flex flex-col gap-2"
      >
        {prompts.map(({ prompt, icon: Icon }) => (
          <m.div key={prompt} variants={ITEM_VARIANTS}>
            <Button
              fullWidth
              variant="light"
              size="sm"
              onPress={() => {
                appendToInput(prompt);
                router.push("/c");
              }}
              className="h-11 justify-start gap-3 rounded-xl bg-zinc-900 px-3 text-sm font-normal text-zinc-300 hover:bg-zinc-700 hover:text-zinc-100"
              startContent={
                <Icon size={18} className="shrink-0 text-zinc-500" />
              }
              endContent={
                <ArrowRight02Icon
                  size={14}
                  className="ml-auto shrink-0 text-zinc-600"
                />
              }
            >
              <span className="truncate text-left">{prompt}</span>
            </Button>
          </m.div>
        ))}
      </m.div>
    </m.div>
  );
}
