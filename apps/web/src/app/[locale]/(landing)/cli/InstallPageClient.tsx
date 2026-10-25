"use client";

import { Button } from "@heroui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
} from "@heroui/table";
import { Tab, Tabs } from "@heroui/tabs";
import { Tooltip } from "@heroui/tooltip";
import {
  CLI_COMMAND_DESCRIPTIONS,
  CLI_INSTALL_COMMANDS,
} from "@shared/cli/command-manifest";
import Image from "next/image";
import Link from "next/link";
import { type ReactNode, useState } from "react";
import CopyButton from "@/components/ui/CopyButton";
import { copyText } from "@/lib/clipboard";
import { siteConfig } from "@/lib/seo";

function InlineCode({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-zinc-800 px-2 py-1 text-sm text-primary">
      {children}
    </code>
  );
}

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
    <div className="flex flex-col items-center space-y-4 py-1">
      <CodeBlock code={code} />
      <p className="text-sm text-zinc-400 text-center">{hint}</p>
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

const commands = [
  { command: "gaia up", description: CLI_COMMAND_DESCRIPTIONS.up },
  { command: "gaia status", description: CLI_COMMAND_DESCRIPTIONS.status },
  { command: "gaia doctor", description: CLI_COMMAND_DESCRIPTIONS.doctor },
  { command: "gaia update", description: CLI_COMMAND_DESCRIPTIONS.update },
  { command: "gaia backup", description: CLI_COMMAND_DESCRIPTIONS.backup },
  { command: "gaia restore", description: CLI_COMMAND_DESCRIPTIONS.restore },
  { command: "gaia logs", description: CLI_COMMAND_DESCRIPTIONS.logs },
  { command: "gaia stop", description: CLI_COMMAND_DESCRIPTIONS.stop },
  { command: "gaia start", description: CLI_COMMAND_DESCRIPTIONS.start },
  {
    command: "gaia uninstall",
    description: CLI_COMMAND_DESCRIPTIONS.uninstall,
  },
  {
    command: "gaia --help",
    description: "Display help and all available commands",
  },
];

export function InstallPageClient() {
  return (
    <div className="relative flex min-h-screen w-full flex-col items-center">
      <div className="w-full max-w-4xl mx-auto mt-24 sm:mt-32 px-4 sm:px-6">
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

      <section className="relative z-10 flex w-full max-w-5xl flex-col items-center gap-4 px-6 mt-5">
        <h1 className="mt-8 text-4xl font-medium text-white sm:text-7xl font-serif">
          Install GAIA
        </h1>
        <p className="max-w-xl text-center text-lg text-zinc-400">
          Run GAIA on your own machine with one command
        </p>
      </section>

      <div className="relative z-10 w-full max-w-5xl space-y-8 pb-6 px-6">
        <div className="flex justify-center mt-8 flex-col">
          <Tabs
            aria-label="Install methods"
            color="primary"
            variant="underlined"
            classNames={{ base: "mx-auto pb-0 mb-0", panel: "pt-3" }}
          >
            {installMethods.map((method) => (
              <Tab key={method.key} title={method.title}>
                <InstallTab code={method.code} hint={method.hint} />
              </Tab>
            ))}
          </Tabs>
        </div>

        <section className="overflow-hidden rounded-3xl bg-zinc-900/50 p-8 backdrop-blur-sm">
          <h2 className="text-3xl font-medium text-white font-serif mb-6">
            Available Commands
          </h2>
          <Table
            aria-label="Available GAIA CLI commands"
            removeWrapper
            classNames={{
              th: "bg-zinc-800 text-zinc-400 font-medium",
              td: "text-zinc-300",
            }}
          >
            <TableHeader>
              <TableColumn>COMMAND</TableColumn>
              <TableColumn>DESCRIPTION</TableColumn>
            </TableHeader>
            <TableBody>
              {commands.map((item) => (
                <TableRow key={item.command}>
                  <TableCell>
                    <InlineCode>{item.command}</InlineCode>
                  </TableCell>
                  <TableCell className="text-sm text-zinc-400">
                    {item.description}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>

        {/* Links Section */}
        <div className="flex justify-center gap-4">
          <Button
            as={Link}
            href="https://docs.heygaia.io/self-hosting/walkthrough"
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
        </div>
      </div>
    </div>
  );
}
