"use client";

import { Button } from "@heroui/button";
import { Tab, Tabs } from "@heroui/tabs";
import { Tooltip } from "@heroui/tooltip";
import { CLI_INSTALL_COMMANDS } from "@shared/cli/command-manifest";
import Image from "next/image";
import Link from "next/link";
import { type ReactNode, useState } from "react";
import FAQAccordion from "@/components/seo/FAQAccordion";
import CopyButton from "@/components/ui/CopyButton";
import InlineCode from "@/components/ui/InlineCode";
import SectionHeader from "@/features/landing/components/demo/founders-demo/SectionHeader";
import NumberedSteps from "@/features/landing/components/shared/NumberedSteps";
import { copyText } from "@/lib/clipboard";
import { siteConfig } from "@/lib/seo";
import {
  CLI_FAQS,
  CLI_REFERENCE_URL,
  SELFHOST_DOCS_URL,
  SELFHOST_REQUIREMENTS,
} from "./cliContent";

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await copyText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy text:", err);
    }
  };

  return (
    <div className="relative flex items-center gap-2 rounded-2xl bg-zinc-900 p-1 px-4 hover:bg-zinc-800/80 transition-colors">
      <Tooltip content={copied ? "Copied!" : "Click to copy"} closeDelay={0}>
        <button
          type="button"
          onClick={handleCopy}
          className="flex-1 cursor-pointer text-left"
        >
          <code className="text-sm text-primary">{code}</code>
        </button>
      </Tooltip>
      <CopyButton textToCopy={code} copied={copied} onCopy={handleCopy} />
    </div>
  );
}

const INSTALLER_COMMAND = "curl -fsSL https://heygaia.io/install.sh | sh";

function InstallTab({ code, hint }: { code: string; hint: ReactNode }) {
  return (
    <div className="flex flex-col space-y-3 py-1">
      <CodeBlock code={code} />
      <p className="text-sm text-zinc-400">{hint}</p>
    </div>
  );
}

const packageManagerHint = (
  <>
    Then run <InlineCode>gaia up</InlineCode> to download GAIA and start it.
  </>
);

const installMethods = [
  {
    key: "installer",
    title: "Installer",
    code: INSTALLER_COMMAND,
    hint: (
      <>
        Installs the GAIA CLI, then offers to run{" "}
        <InlineCode>gaia up</InlineCode>: it installs Docker if it&apos;s
        missing, downloads GAIA and starts it.
      </>
    ),
  },
  {
    key: "npm",
    title: "npm",
    code: CLI_INSTALL_COMMANDS.npm,
    hint: packageManagerHint,
  },
  {
    key: "pnpm",
    title: "pnpm",
    code: CLI_INSTALL_COMMANDS.pnpm,
    hint: packageManagerHint,
  },
  {
    key: "bun",
    title: "bun",
    code: CLI_INSTALL_COMMANDS.bun,
    hint: packageManagerHint,
  },
];

function InstallMethodTabs() {
  return (
    <Tabs
      aria-label="Install methods"
      color="primary"
      variant="underlined"
      classNames={{ base: "pb-0 mb-0", panel: "pt-3" }}
    >
      {installMethods.map((method) => (
        <Tab key={method.key} title={method.title}>
          <InstallTab code={method.code} hint={method.hint} />
        </Tab>
      ))}
    </Tabs>
  );
}

const steps = [
  {
    name: "Check what you need",
    body: (
      <ul className="mt-2 space-y-2">
        {SELFHOST_REQUIREMENTS.map((requirement) => (
          <li key={requirement.label}>
            <span className="text-zinc-200">{requirement.label}.</span>{" "}
            {requirement.detail}
          </li>
        ))}
      </ul>
    ),
  },
  {
    name: "Run one command",
    body: (
      <div className="mt-2">
        <InstallMethodTabs />
      </div>
    ),
  },
  {
    name: "Open GAIA and finish setup",
    body: (
      <div className="space-y-3">
        <p>
          GAIA downloads into <InlineCode>~/gaia</InlineCode> and runs in
          Docker. Open <InlineCode>http://localhost:3000/setup</InlineCode>,
          create the admin account and pick your AI provider. Invite others by
          link from the Members page in Settings.
        </p>
        <p>
          Keep it running with <InlineCode>gaia update</InlineCode>,{" "}
          <InlineCode>gaia backup</InlineCode> and{" "}
          <InlineCode>gaia doctor</InlineCode>. Every command is in the{" "}
          <Link
            href={CLI_REFERENCE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-zinc-200 underline underline-offset-4 hover:text-white"
          >
            CLI reference
          </Link>
          .
        </p>
      </div>
    ),
  },
];

export function InstallPageClient() {
  return (
    <div className="relative flex min-h-screen w-full flex-col items-center">
      <div className="mx-auto mt-24 w-full max-w-4xl px-4 sm:mt-32 sm:px-6">
        <div className="relative aspect-video w-full overflow-hidden rounded-4xl bg-zinc-900">
          <Image
            src="/images/readme/self-host-installer.webp"
            alt="The GAIA installer: Node.js, the GAIA CLI and Docker installed, then GAIA downloading with a progress bar and a row per service"
            width={2400}
            height={1350}
            priority
            sizes="(min-width: 896px) 896px, 100vw"
            className="h-full w-full rounded-4xl object-cover"
          />
        </div>
      </div>

      <section className="relative z-10 mt-5 flex w-full max-w-5xl flex-col items-center gap-4 px-6">
        <h1 className="mt-8 text-center font-serif text-4xl font-medium text-white sm:text-7xl">
          Your own GAIA, on your own machine
        </h1>
        <p className="max-w-xl text-center text-lg text-zinc-400">
          One command sets it up. Your data stays in Docker volumes on your
          machine, and your AI keys stay yours.
        </p>
      </section>

      <section className="relative z-10 w-full max-w-3xl px-6 pt-20">
        <SectionHeader
          label="Self-hosting"
          headline="Three steps to a running GAIA"
          description="From a fresh machine to your assistant in the browser."
        />
        <NumberedSteps steps={steps} />
      </section>

      <section className="relative z-10 w-full max-w-3xl px-6 pt-20">
        <h2 className="mb-8 text-center font-serif text-4xl font-normal text-white sm:text-5xl">
          Questions, answered
        </h2>
        <FAQAccordion faqs={CLI_FAQS} />
      </section>

      <div className="relative z-10 flex flex-wrap justify-center gap-4 px-6 pb-24 pt-12">
        <Button
          as={Link}
          href={SELFHOST_DOCS_URL}
          color="primary"
          target="_blank"
          rel="noopener noreferrer"
        >
          Read the self-hosting guide
        </Button>
        <Button
          as={Link}
          href={siteConfig.links.repo}
          variant="bordered"
          target="_blank"
          rel="noopener noreferrer"
        >
          View on GitHub
        </Button>
        <Button as={Link} href="/open-source-ai-assistant" variant="light">
          Why self-host GAIA
        </Button>
      </div>
    </div>
  );
}
