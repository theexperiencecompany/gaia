"use client";

import {
  AiBrain01Icon,
  Calendar01Icon,
  ComputerIcon,
  ConnectIcon,
  Home01Icon,
  SquareLock02Icon,
  UserCircle02Icon,
  ZapIcon,
} from "@icons";
import { shuffle } from "lodash";
import Image from "next/image";
import Link from "next/link";
import { useMemo } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

interface FeatureStatus {
  description: React.ReactNode;
}

interface Integration {
  id: string;
  name: string;
}

interface ComparisonFeature {
  icon: React.ReactNode;
  title: string;
  gaia: FeatureStatus;
  chatgpt: FeatureStatus;
  gemini: FeatureStatus;
}

interface ComparisonTableProps {
  integrations: Integration[];
  isLoading: boolean;
  hasMessages: boolean;
}

function AppConnectionsIcons({
  integrations = [],
  isLoading = false,
  hasMessages = false,
}: {
  integrations: Integration[];
  isLoading: boolean;
  hasMessages: boolean;
}) {
  const shuffledIntegrations = useMemo(
    () => shuffle(integrations.slice(0, 9)),
    [integrations],
  );
  if (isLoading || integrations.length === 0 || hasMessages) return null;
  return (
    <div className="flex items-center gap-1">
      {shuffledIntegrations.map((integration) => (
        <span
          key={integration.id}
          title={integration.name}
          className="opacity-60 transition duration-200 hover:scale-150 hover:rotate-6 hover:opacity-100"
        >
          {getToolCategoryIcon(integration.id, {
            size: 14,
            width: 14,
            height: 14,
            showBackground: false,
            className: "h-[18px] w-[18px] object-contain",
          })}
        </span>
      ))}
      <span className="ml-1 text-lg leading-none opacity-60">…</span>
    </div>
  );
}

export function ComparisonTable({
  integrations = [],
  isLoading = false,
  hasMessages = false,
}: ComparisonTableProps) {
  const comparisonFeatures: ComparisonFeature[] = [
    {
      icon: <AiBrain01Icon className="h-5 w-5 text-primary" />,
      title: "Overwhelmed by emails",
      gaia: { description: "I'll sort, label, and reply for you." },
      chatgpt: { description: "Paste the email in here." },
      gemini: { description: "Paste the email in here." },
    },
    {
      icon: <Calendar01Icon className="h-5 w-5 text-primary" />,
      title: "Forgetting things",
      gaia: { description: "Already added to your calendar." },
      chatgpt: { description: "Ask me to remind you first." },
      gemini: { description: "You remind it." },
    },
    {
      icon: <ZapIcon className="h-5 w-5 text-primary" />,
      title: "Repeating tasks",
      gaia: { description: "I'll automate it daily." },
      chatgpt: { description: "Prompt it again." },
      gemini: { description: "Prompt it again." },
    },
    {
      icon: <ComputerIcon className="h-5 w-5 text-primary" />,
      title: "Need fast reports",
      gaia: { description: "Here's your doc. Ready." },
      chatgpt: { description: "Explains. Doesn't act." },
      gemini: { description: "Tells you. Doesn't do." },
    },
    {
      icon: <SquareLock02Icon className="h-5 w-5 text-primary" />,
      title: "Privacy concerns",
      gaia: { description: "Open-source. Self-hosted. Yours." },
      chatgpt: { description: "Trains on your data." },
      gemini: { description: "Trains on your data." },
    },
    {
      icon: <UserCircle02Icon className="h-5 w-5 text-primary" />,
      title: "Personal memory",
      gaia: { description: "I remember your habits." },
      chatgpt: { description: "What did we talk about?" },
      gemini: { description: "Remind me again?" },
    },
    {
      icon: <AiBrain01Icon className="h-5 w-5 text-primary" />,
      title: "Get work done",
      gaia: { description: "Done. Already." },
      chatgpt: { description: "Explains. Doesn't act." },
      gemini: { description: "Tells you. Doesn't do." },
    },
    {
      icon: <Home01Icon className="h-5 w-5 text-primary" />,
      title: "Personalization",
      gaia: { description: "Change anything. It's yours." },
      chatgpt: { description: "You get what we give." },
      gemini: { description: "You get what we give." },
    },
    {
      icon: <ConnectIcon className="h-5 w-5 text-primary" />,
      title: "App connections",
      gaia: {
        description: (
          <AppConnectionsIcons
            integrations={integrations}
            isLoading={isLoading}
            hasMessages={hasMessages}
          />
        ),
      },
      chatgpt: { description: "No real integrations." },
      gemini: { description: "No real integrations." },
    },
    {
      icon: <ZapIcon className="h-5 w-5 text-primary" />,
      title: "Proactive help",
      gaia: { description: "I act before you ask." },
      chatgpt: { description: "No workflows." },
      gemini: { description: "No workflows." },
    },
  ];

  function CompanyHeader({
    name,
    logo,
    description,
    isGaia = false,
  }: {
    name: string;
    logo: string;
    description: string;
    isGaia?: boolean;
  }) {
    return (
      <div
        className={[
          "rounded-2xl px-4 py-3 text-center transition-all",
          isGaia ? "bg-primary/5 ring-1 ring-primary/15" : "bg-transparent",
        ].join(" ")}
      >
        <div className="mb-3 flex items-center justify-center">
          <Image
            src={logo}
            alt={`${name} Logo`}
            width={40}
            height={40}
            className="rounded-xl"
          />
        </div>
        <h3
          className={`mb-1 text-xl font-semibold ${isGaia ? "text-white" : "text-zinc-300"}`}
        >
          {name}
        </h3>
        <p className={`text-xs ${isGaia ? "text-zinc-400" : "text-zinc-500"}`}>
          {description}
        </p>
      </div>
    );
  }

  function FeatureStatusCell({
    status,
    highlight = false,
  }: {
    status: FeatureStatus;
    highlight?: boolean;
  }) {
    return (
      <div
        className={[
          "flex flex-col items-center gap-2 rounded-lg px-2 py-1",
          highlight ? "bg-primary/4" : "",
        ].join(" ")}
      >
        <span
          className={`max-w-48 text-center text-sm leading-snug ${
            highlight ? "font-medium text-primary" : "text-zinc-500"
          }`}
        >
          {status.description}
        </span>
      </div>
    );
  }

  function FeatureRow({ feature }: { feature: ComparisonFeature }) {
    return (
      <div className="group grid grid-cols-4 items-center gap-6 rounded-xl border-b border-white/5 px-2 py-2.5 transition-colors hover:bg-zinc-800/40">
        <div className="flex items-center gap-3">
          {feature.icon}
          <span className="text-base font-medium text-zinc-100">
            {feature.title}
          </span>
        </div>
        <div className="flex items-center justify-center">
          <FeatureStatusCell status={feature.gaia} highlight />
        </div>
        <div className="flex items-center justify-center">
          <FeatureStatusCell status={feature.chatgpt} />
        </div>
        <div className="flex items-center justify-center">
          <FeatureStatusCell status={feature.gemini} />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl py-16">
      <div className="mb-10 flex w-full flex-col items-center justify-center gap-2 text-white">
        <h1 className="text-center font-serif text-6xl font-normal tracking-tight">
          One assistant. Zero excuses.
        </h1>
        <span className="text-lg font-light text-zinc-400">
          GAIA acts. The rest advise.
        </span>
      </div>

      <div className="relative overflow-hidden rounded-4xl bg-zinc-900/60 p-8 shadow-xl backdrop-blur-md">
        <div className="mb-6 grid grid-cols-4 gap-4">
          <div />
          <CompanyHeader
            name="GAIA"
            logo="/images/logos/logo.webp"
            description="Your proactive AI assistant"
            isGaia
          />
          <CompanyHeader
            name="ChatGPT"
            logo="https://static.vecteezy.com/system/resources/previews/024/558/807/non_2x/openai-chatgpt-logo-icon-free-png.png"
            description="Conversational AI chatbot"
          />
          <CompanyHeader
            name="Gemini"
            logo="https://static.vecteezy.com/system/resources/previews/055/687/055/non_2x/rectangle-gemini-google-icon-symbol-logo-free-png.png"
            description="Google's AI assistant"
          />
        </div>

        <div className="space-y-1">
          {comparisonFeatures.map((feature) => (
            <FeatureRow key={feature.title} feature={feature} />
          ))}
        </div>

        <div className="mt-10 flex justify-center">
          <Link href={"/signup"}>
            <RaisedButton
              size={"lg"}
              className="rounded-xl text-lg text-black!"
              color="#00bbff"
            >
              Try GAIA Free
            </RaisedButton>
          </Link>
        </div>
      </div>
    </div>
  );
}
