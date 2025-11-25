"use client";

import { shuffle } from "lodash";
import Image from "next/image";
import Link from "next/link";
import { useMemo } from "react";

import { RaisedButton } from "@/components/ui/raised-button";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  AiBrain01Icon,
  Calendar01Icon,
  ComputerIcon,
  ConnectIcon,
  Home01Icon,
  SquareLock02Icon,
  UserCircle02Icon,
  ZapIcon,
} from "@/icons";

interface FeatureStatus {
  // description: string;
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
          className="opacity-60 transition duration-200 hover:scale-150 hover:rotate-6 hover:opacity-120"
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
      icon: <AiBrain01Icon className="h-6 w-6 text-primary" />,
      title: "Overwhelmed by emails",
      gaia: { description: "I’ll sort, label, and reply for you." },
      chatgpt: { description: "Copy the email here." },
      gemini: { description: "Copy the email here." },
    },
    {
      icon: <Calendar01Icon className="h-6 w-6 text-primary" />,
      title: "Forgetting things",
      gaia: { description: "Already added to your calendar." },
      chatgpt: { description: "Remind you… if you type it." },
      gemini: { description: "Remind you… manually." },
    },
    // {
    //   icon: <ConnectIcon className="h-6 w-6 text-primary" />,
    //   title: "Scattered files",
    //   gaia: { description: "I remember every file. Ask me." },
    //   chatgpt: { description: "Upload again?" },
    //   gemini: { description: "Maybe I recall it… maybe not." },
    // },
    {
      icon: <ZapIcon className="h-6 w-6 text-primary" />,
      title: "Repeating tasks",
      gaia: { description: "I’ll automate it daily." },
      chatgpt: { description: "Type it again?" },
      gemini: { description: "Repeat it… again?" },
    },
    {
      icon: <ComputerIcon className="h-6 w-6 text-primary" />,
      title: "Need fast reports",
      gaia: { description: "Here’s your doc. Ready." },
      chatgpt: { description: "I write, you finish." },
      gemini: { description: "Same." },
    },
    {
      icon: <SquareLock02Icon className="h-6 w-6 text-primary" />,
      title: "Privacy concerns",
      gaia: { description: "All yours. Open-source and self-hosted." },
      chatgpt: { description: "Trust us." },
      gemini: { description: "Trust us." },
    },
    {
      icon: <UserCircle02Icon className="h-6 w-6 text-primary" />,
      title: "Personal memory",
      gaia: { description: "I remember your habits." },
      chatgpt: { description: "What did we talk about?" },
      gemini: { description: "Remind me again?" },
    },
    {
      icon: <AiBrain01Icon className="h-6 w-6 text-primary" />,
      title: "Get work done",
      gaia: { description: "On it. Executing." },
      chatgpt: { description: "Here’s the theory." },
      gemini: { description: "Here’s an answer." },
    },
    {
      icon: <Home01Icon className="h-6 w-6 text-primary" />,
      title: "Personalization",
      gaia: { description: "Change anything. It’s yours." },
      chatgpt: { description: "You get what we give." },
      gemini: { description: "You get what we give." },
    },
    {
      icon: <ConnectIcon className="h-6 w-6 text-primary" />,
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
      icon: <ZapIcon className="h-6 w-6 text-primary" />,
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
  }: {
    name: string;
    logo: string;
    description: string;
  }) {
    return (
      <div className="text-center">
        <div className="mb-3 flex items-center justify-center">
          <Image
            src={logo}
            alt={`${name} Logo`}
            width={48}
            height={48}
            className="rounded-2xl"
          />
        </div>
        <h3 className="mb-1 text-2xl font-semibold">{name}</h3>
        <p className="text-sm text-gray-400">{description}</p>
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
      <div className="flex flex-col items-center gap-2">
        <span
          className={`max-w-48 text-center text-sm leading-snug ${
            highlight ? "font-semibold text-primary" : "text-zinc-400"
          }`}
        >
          {status.description}
        </span>
      </div>
    );
  }

  function FeatureRow({ feature }: { feature: ComparisonFeature }) {
    return (
      <div className="group grid grid-cols-4 items-center gap-6 rounded-xl border-b border-white/5 px-2 py-2 transition-colors hover:bg-zinc-800/40">
        <div className="flex items-center gap-3">
          {feature.icon}
          <span className="text-lg font-semibold text-zinc-100">
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
      <div className="mb-10 flex w-full flex-col items-center justify-center gap-3 text-white">
        <h1 className="text-center font-serif text-6xl font-normal">
          See how GAIA stacks up against the competition.
        </h1>
        <span className="text-xl font-light text-zinc-300">
          What makes GAIA better and not just a "chatbot"
        </span>
      </div>

      <div className="relative overflow-hidden rounded-4xl bg-zinc-900/60 p-8 shadow-xl backdrop-blur-md">
        <div className="mb-6 grid grid-cols-4 gap-6">
          <div />
          <CompanyHeader
            name="GAIA"
            logo="/images/logos/logo.webp"
            description="Your proactive AI assistant"
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

        <div className="space-y-6">
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
              Let's Go!
            </RaisedButton>
          </Link>
        </div>
      </div>
    </div>
  );
}
