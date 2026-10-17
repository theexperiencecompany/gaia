"use client";

import { CheckmarkCircle02Icon, Tick02Icon } from "@icons";
import * as m from "motion/react-m";
import Image from "next/image";
import { providerFaviconUrl } from "@/features/settings/api/providersApi";
import type { CatalogProvider } from "@/features/settings/utils/providerCatalog";
import { CARD_TRANSITION, CARD_VARIANTS, ITEM_VARIANTS } from "./doneMotion";

interface ReadyCardProps {
  /** Connected LLM providers, the first one featured in the status chip. */
  connectedLlmCards: CatalogProvider[];
}

export function ReadyCard({ connectedLlmCards }: ReadyCardProps) {
  const primaryLlm = connectedLlmCards[0] ?? null;

  return (
    <m.div
      variants={CARD_VARIANTS}
      transition={CARD_TRANSITION}
      className="w-full rounded-2xl bg-zinc-800 p-6 text-center"
    >
      <m.div
        initial={{ opacity: 0, scale: 0.6, rotate: -12 }}
        animate={{ opacity: 1, scale: 1, rotate: 0 }}
        transition={{
          type: "spring",
          stiffness: 320,
          damping: 18,
          delay: 0.15,
        }}
        className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-400/10"
      >
        <CheckmarkCircle02Icon size={28} className="text-emerald-400" />
      </m.div>
      <m.p
        variants={ITEM_VARIANTS}
        transition={{ duration: 0.35, delay: 0.22 }}
        className="mt-4 text-xl font-semibold tracking-tight text-zinc-100"
      >
        You're ready to chat
      </m.p>
      <m.p
        variants={ITEM_VARIANTS}
        transition={{ duration: 0.35, delay: 0.28 }}
        className="mx-auto mt-1 max-w-sm text-sm leading-relaxed text-zinc-400"
      >
        Connected and ready to help. Try one of the prompts below or start
        chatting on your own.
      </m.p>
      {primaryLlm && (
        <m.div
          variants={ITEM_VARIANTS}
          transition={{ duration: 0.35, delay: 0.34 }}
          className="mt-4 inline-flex items-center gap-2 rounded-full bg-zinc-900 px-3 py-1.5"
        >
          <Image
            src={providerFaviconUrl(primaryLlm.favicon_domain)}
            alt={`${primaryLlm.label} favicon`}
            width={16}
            height={16}
            className="rounded-sm"
          />
          <span className="text-xs font-medium text-zinc-200">
            Connected to {primaryLlm.label}
          </span>
          <span className="h-3 w-px bg-zinc-700" />
          <span className="flex items-center gap-1 text-xs text-emerald-400">
            <Tick02Icon height={12} className="shrink-0" />
            Ready
          </span>
          {connectedLlmCards.length > 1 && (
            <>
              <span className="h-3 w-px bg-zinc-700" />
              <span className="text-xs text-zinc-500">
                +{connectedLlmCards.length - 1} more
              </span>
            </>
          )}
        </m.div>
      )}
    </m.div>
  );
}
