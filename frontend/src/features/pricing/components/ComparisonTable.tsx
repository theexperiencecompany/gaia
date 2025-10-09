"use client";

import { Chip } from "@heroui/chip";
import Image from "next/image";

import {
  AiBrain01Icon,
  Brain02Icon,
  Calendar01Icon,
  CheckmarkCircle02Icon,
  ComputerIcon,
  ConnectIcon,
  Home01Icon,
  Mail01Icon,
  RemoveCircleIcon,
  SquareLock02Icon,
  UserCircle02Icon,
  ZapIcon,
} from "@/components/shared/icons";
import { RaisedButton } from "@/components/ui/shadcn/raised-button";
import Link from "next/link";

interface FeatureStatus {
  available: boolean;
  description: string;
}

interface ComparisonFeature {
  icon: React.ReactNode;
  title: string;
  gaia: FeatureStatus;
  chatgpt: FeatureStatus;
  gemini: FeatureStatus;
}

const comparisonFeatures: ComparisonFeature[] = [
  {
    icon: <AiBrain01Icon className="h-6 w-6 text-primary" />,
    title: "Proactive & Autonomous",
    gaia: {
      available: true,
      description: "Auto-watches inbox & calendar",
    },
    chatgpt: {
      available: false,
      description: "Reactive chat only",
    },
    gemini: {
      available: false,
      description: "Reactive in Google apps",
    },
  },
  {
    icon: <Brain02Icon className="h-6 w-6 text-primary" />,
    title: "Personal Memory",
    gaia: {
      available: true,
      description: "Learns your habits & preferences",
    },
    chatgpt: {
      available: false,
      description: "Limited per-thread memory",
    },
    gemini: {
      available: false,
      description: "Not persistent across sessions",
    },
  },
  {
    icon: <ConnectIcon className="h-6 w-6 text-primary" />,
    title: "Cross-Tool Actions",
    gaia: {
      available: true,
      description: "Gmail, Calendar, Drive & desktop",
    },
    chatgpt: {
      available: false,
      description: "Limited tool integrations",
    },
    gemini: {
      available: false,
      description: "Google apps only",
    },
  },
  {
    icon: <Home01Icon className="h-6 w-6 text-primary" />,
    title: "Self-Hosting",
    gaia: {
      available: true,
      description: "Open-source & self-hostable",
    },
    chatgpt: {
      available: false,
      description: "Closed, OpenAI hosted",
    },
    gemini: {
      available: false,
      description: "Closed, Google hosted",
    },
  },
  {
    icon: <Mail01Icon className="h-6 w-6 text-primary" />,
    title: "Email Management",
    gaia: {
      available: true,
      description: "Auto-prioritize, draft & send",
    },
    chatgpt: {
      available: false,
      description: "Drafting only",
    },
    gemini: {
      available: false,
      description: "Summaries, limited actions",
    },
  },
  {
    icon: <Calendar01Icon className="h-6 w-6 text-primary" />,
    title: "Calendar Automation",
    gaia: {
      available: true,
      description: "Auto-scheduling & reminders",
    },
    chatgpt: {
      available: false,
      description: "Suggestions only",
    },
    gemini: {
      available: false,
      description: "Basic suggestions",
    },
  },
  {
    icon: <ComputerIcon className="h-6 w-6 text-primary" />,
    title: "Desktop Automation",
    gaia: {
      available: true,
      description: "Controls websites & desktop apps",
    },
    chatgpt: {
      available: false,
      description: "Requires external tools",
    },
    gemini: {
      available: false,
      description: "Google properties only",
    },
  },
  {
    icon: <UserCircle02Icon className="h-6 w-6 text-primary" />,
    title: "Personal Experience",
    gaia: {
      available: true,
      description: "Friendly, consistent partner",
    },
    chatgpt: {
      available: false,
      description: "Less persistent persona",
    },
    gemini: {
      available: false,
      description: "Less personal feel",
    },
  },
  {
    icon: <SquareLock02Icon className="h-6 w-6 text-primary" />,
    title: "Data Control",
    gaia: {
      available: true,
      description: "Full control over data & hosting",
    },
    chatgpt: {
      available: false,
      description: "Vendor-managed storage",
    },
    gemini: {
      available: false,
      description: "Google-managed storage",
    },
  },
  {
    icon: <ZapIcon className="h-6 w-6 text-primary" />,
    title: "Setup & Workflow",
    gaia: {
      available: true,
      description: "Simple chat setup, broad integrations",
    },
    chatgpt: {
      available: false,
      description: "Needs configuration for actions",
    },
    gemini: {
      available: false,
      description: "Limited beyond Google",
    },
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

function FeatureStatusCell({ status }: { status: FeatureStatus }) {
  return (
    <div className="flex flex-col items-center gap-2">
      <div
        className={`flex items-center justify-center rounded-full p-1 ${
          status.available ? "bg-green-400/10" : "bg-red-400/10"
        }`}
      >
        {status.available ? (
          <CheckmarkCircle02Icon className="h-8 w-8 text-green-600" />
        ) : (
          <RemoveCircleIcon className="h-7 w-7 text-red-600" />
        )}
      </div>
      <span className="max-w-32 text-center text-xs leading-tight text-gray-400">
        {status.description}
      </span>
    </div>
  );
}

function FeatureRow({ feature }: { feature: ComparisonFeature }) {
  return (
    <div className="grid grid-cols-4 items-center gap-6 border-b border-white/5 py-3 last:border-b-0">
      <div className="flex items-center gap-3">
        {feature.icon}
        <span className="text-lg font-medium">{feature.title}</span>
      </div>
      <div className="flex items-center justify-center">
        <FeatureStatusCell status={feature.gaia} />
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

export function ComparisonTable() {
  return (
    <div className="mx-auto w-full max-w-7xl px-6 py-16">
      <div className="mb-12 text-center">
        <h2 className="mb-4 text-5xl font-semibold">
          See how GAIA stacks up against the competition.
        </h2>
        <p className="text-lg text-gray-400">
          What makes GAIA better and not just a "chatbot"
        </p>
      </div>

      <div className="relative overflow-hidden rounded-3xl border-1 border-zinc-800 bg-zinc-900/80 p-8 backdrop-blur-sm">
        <div className="mb-8 grid grid-cols-4 gap-6">
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
          {comparisonFeatures.map((feature, index) => (
            <FeatureRow key={index} feature={feature} />
          ))}
        </div>

        <div className="mt-12 flex justify-center">
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
