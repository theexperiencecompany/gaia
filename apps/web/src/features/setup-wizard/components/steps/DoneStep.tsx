/**
 * Wizard step 4 — summary of everything configured, marks the wizard
 * complete (POST /setup/complete {step:"wizard"}), and hands the user off
 * to chat. The celebratory "ready" card + starter prompts make the empty
 * chat feel intentional; the skipped-provider branch nudges toward Settings
 * without blocking.
 */

"use client";

import { Button } from "@heroui/button";
import {
  Alert01Icon,
  ArrowRight02Icon,
  CheckmarkCircle02Icon,
  CodeIcon,
  GlobalIcon,
  Mail01Icon,
  SparklesIcon,
  Tick02Icon,
} from "@icons";
import * as m from "motion/react-m";
import nextDynamic from "next/dynamic";
import Image from "next/image";
import Link from "next/link";
import { type ReactNode, useEffect } from "react";
import {
  providerFaviconUrl,
  type SetupStatus,
} from "@/features/settings/api/providersApi";
import {
  isAnyLlmConfigured,
  isProviderConfigured,
} from "@/features/settings/hooks/useSetupStatus";
import { apiService } from "@/lib/api/service";
import { useAppendToInput } from "@/stores/composerStore";
import {
  LLM_PROVIDER_CARDS,
  SEARCH_PROVIDER_CARD,
  TOOL_PROVIDER_CARDS,
} from "../../constants";

const ConnectedAppsCount = nextDynamic(() => import("./ConnectedAppsCount"), {
  ssr: false,
});

interface DoneStepProps {
  status: SetupStatus;
}

function providerLabel(key: string): string {
  return (
    [...LLM_PROVIDER_CARDS, SEARCH_PROVIDER_CARD, ...TOOL_PROVIDER_CARDS].find(
      (card) => card.key === key,
    )?.label ?? key
  );
}

const STARTER_PROMPTS: Array<{
  prompt: string;
  icon: typeof GlobalIcon;
}> = [
  {
    prompt: "Search the web for today's AI headlines",
    icon: GlobalIcon,
  },
  {
    prompt: "Run a Python script that prints hello world",
    icon: CodeIcon,
  },
  {
    prompt: "Help me organize my inbox",
    icon: Mail01Icon,
  },
];

export function DoneStep({ status }: DoneStepProps) {
  useEffect(() => {
    apiService
      .post("setup/complete", { step: "wizard" }, { silent: true })
      .catch((err: unknown) => {
        console.error("Failed to mark setup complete:", err);
      });
  }, []);

  const appendToInput = useAppendToInput();

  const connectedLlmCards = LLM_PROVIDER_CARDS.filter((card) =>
    isProviderConfigured(status, card.key),
  );
  const hasLlm = isAnyLlmConfigured(status);
  const primaryLlm = connectedLlmCards[0] ?? null;

  const searchConfigured = isProviderConfigured(
    status,
    SEARCH_PROVIDER_CARD.key,
  );

  const connectedTools = TOOL_PROVIDER_CARDS.filter((card) =>
    isProviderConfigured(status, card.key),
  );

  // Subtle confetti burst when the GAIA is ready — single fire, no loop.
  useEffect(() => {
    if (!hasLlm) return;
    let cancelled = false;
    import("canvas-confetti").then(({ default: confetti }) => {
      if (cancelled) return;
      confetti({
        particleCount: 90,
        spread: 70,
        origin: { y: 0.65 },
        ticks: 180,
        gravity: 1.1,
        decay: 0.94,
        scalar: 0.9,
        colors: ["#00bbff", "#a78bfa", "#34d399", "#f472b6"],
      });
    });
    return () => {
      cancelled = true;
    };
  }, [hasLlm]);

  return (
    <m.div
      className="flex w-full flex-col gap-3"
      initial="hidden"
      animate="visible"
      variants={{
        hidden: {},
        visible: { transition: { staggerChildren: 0.08, delayChildren: 0.05 } },
      }}
    >
      {hasLlm ? (
        <m.div
          variants={{
            hidden: { opacity: 0, y: 12 },
            visible: { opacity: 1, y: 0 },
          }}
          transition={{ duration: 0.4, ease: [0.19, 1, 0.22, 1] }}
          className="w-full rounded-2xl bg-zinc-800 p-6 text-center"
        >
          <m.div
            initial={{ scale: 0, rotate: -12 }}
            animate={{ scale: 1, rotate: 0 }}
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
            variants={{
              hidden: { opacity: 0, y: 8 },
              visible: { opacity: 1, y: 0 },
            }}
            transition={{ duration: 0.35, delay: 0.22 }}
            className="mt-4 text-xl font-semibold tracking-tight text-zinc-100"
          >
            Your GAIA is ready!
          </m.p>
          <m.p
            variants={{
              hidden: { opacity: 0, y: 8 },
              visible: { opacity: 1, y: 0 },
            }}
            transition={{ duration: 0.35, delay: 0.28 }}
            className="mx-auto mt-1 max-w-sm text-sm leading-relaxed text-zinc-400"
          >
            Connected and ready to help. Try one of the prompts below or start
            chatting on your own.
          </m.p>
          {primaryLlm && (
            <m.div
              variants={{
                hidden: { opacity: 0, y: 8 },
                visible: { opacity: 1, y: 0 },
              }}
              transition={{ duration: 0.35, delay: 0.34 }}
              className="mt-4 inline-flex items-center gap-2 rounded-full bg-zinc-900 px-3 py-1.5"
            >
              <Image
                src={providerFaviconUrl(primaryLlm.faviconDomain)}
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
      ) : (
        <m.div
          variants={{
            hidden: { opacity: 0, y: 12 },
            visible: { opacity: 1, y: 0 },
          }}
          transition={{ duration: 0.4, ease: [0.19, 1, 0.22, 1] }}
          className="w-full rounded-2xl bg-zinc-800 p-6"
        >
          <div className="flex gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-amber-400/10">
              <Alert01Icon size={18} className="text-amber-400" />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-zinc-100">
                You skipped provider setup
              </p>
              <p className="mt-1 text-sm leading-relaxed text-zinc-400">
                GAIA will use local fallbacks where available. Add a key in{" "}
                <span className="font-medium text-zinc-300">
                  Settings → AI Providers
                </span>{" "}
                to unlock full power — one key is all it takes to start
                chatting.
              </p>
              <Button
                as={Link}
                href="/settings/providers"
                size="sm"
                variant="flat"
                className="mt-3"
              >
                Go to Settings
              </Button>
            </div>
          </div>
        </m.div>
      )}

      {hasLlm && (
        <m.div
          variants={{
            hidden: { opacity: 0, y: 12 },
            visible: { opacity: 1, y: 0 },
          }}
          transition={{ duration: 0.4, ease: [0.19, 1, 0.22, 1] }}
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
            {STARTER_PROMPTS.map(({ prompt, icon: Icon }) => (
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
      )}

      <m.div
        variants={{
          hidden: { opacity: 0, y: 12 },
          visible: { opacity: 1, y: 0 },
        }}
        transition={{ duration: 0.4, ease: [0.19, 1, 0.22, 1] }}
        className="w-full rounded-2xl bg-zinc-800 p-4"
      >
        <p className="mb-3 text-sm font-semibold text-zinc-100">
          Instance summary
        </p>
        <div className="space-y-2">
          <SummaryRow
            label="AI provider"
            value={
              connectedLlmCards.length > 0
                ? connectedLlmCards.map((c) => c.label).join(", ")
                : "Not set up"
            }
            done={connectedLlmCards.length > 0}
          />
          <SummaryRow
            label="Web search"
            value={
              searchConfigured
                ? providerLabel(SEARCH_PROVIDER_CARD.key)
                : "Skipped"
            }
            done={searchConfigured}
          />
          <SummaryRow
            label="Tool keys"
            value={
              connectedTools.length > 0
                ? connectedTools.map((card) => card.label).join(", ")
                : "None yet"
            }
            done={null}
          />
          <SummaryRow
            label="Connected accounts"
            value={<ConnectedAppsCount />}
            done={null}
          />
          <SummaryRow
            label="Admin account"
            value={status.has_admin_account ? "Active" : "Pending"}
            done={status.has_admin_account}
          />
        </div>
      </m.div>

      <m.div
        variants={{
          hidden: { opacity: 0, y: 12 },
          visible: { opacity: 1, y: 0 },
        }}
        transition={{ duration: 0.4, ease: [0.19, 1, 0.22, 1] }}
      >
        <Button
          as={Link}
          href="/c"
          color="primary"
          fullWidth
          size="lg"
          className="font-medium"
          endContent={<ArrowRight02Icon size={18} />}
        >
          Start chatting
        </Button>
      </m.div>
      {!searchConfigured && (
        <m.p
          variants={{
            hidden: { opacity: 0 },
            visible: { opacity: 1 },
          }}
          transition={{ duration: 0.35, delay: 0.2 }}
          className="text-center text-xs text-zinc-500"
        >
          Skipped something? You can finish anytime from Settings → Providers.
        </m.p>
      )}
    </m.div>
  );
}

function SummaryRow({
  label,
  value,
  done,
}: {
  label: string;
  value: ReactNode;
  /** null = informational row without a done/pending verdict */
  done: boolean | null;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-zinc-900 p-3">
      <span className="text-sm font-medium text-zinc-200">{label}</span>
      <span className="flex items-center gap-1.5 text-xs text-zinc-400">
        {done !== null && done && (
          <Tick02Icon height={14} className="text-emerald-400" />
        )}
        {value}
      </span>
    </div>
  );
}
