"use client";

import { Button, Table, Tabs, Tooltip } from "@heroui/react";
import {
  CLI_COMMAND_DESCRIPTIONS,
  CLI_INSTALL_COMMANDS,
} from "@shared/cli/command-manifest";
import Link from "next/link";
import { type ComponentProps, type ReactNode, useState } from "react";
import FAQAccordion from "@/components/seo/FAQAccordion";
import CopyButton from "@/components/ui/CopyButton";
import InlineCode from "@/components/ui/InlineCode";
import ProgressiveImage from "@/components/ui/ProgressiveImage";
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
      <Tooltip closeDelay={0}>
        <Tooltip.Trigger className="flex-1">
          <button
            type="button"
            onClick={handleCopy}
            className="w-full cursor-pointer text-left"
          >
            <code className="text-sm text-primary">{code}</code>
          </button>
        </Tooltip.Trigger>
        <Tooltip.Content>
          {copied ? "Copied!" : "Click to copy"}
        </Tooltip.Content>
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

const cliCommands = [
  { command: "gaia up", description: CLI_COMMAND_DESCRIPTIONS.up },
  { command: "gaia status", description: CLI_COMMAND_DESCRIPTIONS.status },
  { command: "gaia logs", description: CLI_COMMAND_DESCRIPTIONS.logs },
  { command: "gaia stop", description: CLI_COMMAND_DESCRIPTIONS.stop },
  { command: "gaia start", description: CLI_COMMAND_DESCRIPTIONS.start },
  { command: "gaia update", description: CLI_COMMAND_DESCRIPTIONS.update },
  { command: "gaia doctor", description: CLI_COMMAND_DESCRIPTIONS.doctor },
  { command: "gaia backup", description: CLI_COMMAND_DESCRIPTIONS.backup },
  { command: "gaia restore", description: CLI_COMMAND_DESCRIPTIONS.restore },
  {
    command: "gaia uninstall",
    description: CLI_COMMAND_DESCRIPTIONS.uninstall,
  },
];

function InstallMethodTabs() {
  return (
    <Tabs variant="secondary" className="mb-0 pb-0">
      <Tabs.ListContainer>
        <Tabs.List aria-label="Install methods">
          {installMethods.map((method) => (
            <Tabs.Tab key={method.key} id={method.key}>
              {method.title}
              <Tabs.Indicator />
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs.ListContainer>
      {installMethods.map((method) => (
        <Tabs.Panel key={method.key} id={method.key} className="pt-3">
          <InstallTab code={method.code} hint={method.hint} />
        </Tabs.Panel>
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
          <ProgressiveImage
            webpSrc="/images/screenshots/cli.webp"
            pngSrc="/images/screenshots/cli.png"
            alt="GAIA CLI"
            width={1920}
            height={1080}
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
          Available commands
        </h2>
        <Table>
          <Table.Content aria-label="Available GAIA CLI commands">
            <Table.Header>
              <Table.Column isRowHeader>Command</Table.Column>
              <Table.Column>Description</Table.Column>
            </Table.Header>
            <Table.Body>
              {cliCommands.map((item) => (
                <Table.Row key={item.command} id={item.command}>
                  <Table.Cell>
                    <InlineCode>{item.command}</InlineCode>
                  </Table.Cell>
                  <Table.Cell>{item.description}</Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table.Content>
        </Table>
      </section>

      <section className="relative z-10 w-full max-w-3xl px-6 pt-20">
        <h2 className="mb-8 text-center font-serif text-4xl font-normal text-white sm:text-5xl">
          Questions, answered
        </h2>
        <FAQAccordion faqs={CLI_FAQS} />
      </section>

      <div className="relative z-10 flex flex-wrap justify-center gap-4 px-6 pb-24 pt-12">
        <Button
          render={(props) => (
            <Link
              {...(props as unknown as ComponentProps<"a">)}
              href={SELFHOST_DOCS_URL}
              target="_blank"
              rel="noopener noreferrer"
            />
          )}
          variant="primary"
        >
          Read Full Documentation
        </Button>
        <Button
          render={(props) => (
            <Link
              {...(props as unknown as ComponentProps<"a">)}
              href={siteConfig.links.repo}
              target="_blank"
              rel="noopener noreferrer"
            />
          )}
          variant="secondary"
        >
          View on GitHub
        </Button>
        <Button
          render={(props) => (
            <Link
              {...(props as unknown as ComponentProps<"a">)}
              href="/open-source-ai-assistant"
            />
          )}
          variant="tertiary"
        >
          Why self-host GAIA
        </Button>
      </div>
    </div>
  );
}
