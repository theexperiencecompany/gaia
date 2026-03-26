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
import { CLI_COMMAND_DESCRIPTIONS } from "@shared/cli/command-manifest";
import Link from "next/link";
import { type ReactNode, useState } from "react";
import CopyButton from "@/components/ui/CopyButton";
import ProgressiveImage from "@/components/ui/ProgressiveImage";

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
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy text:", err);
    }
  };

  return (
    <Tooltip content={copied ? "Copied!" : "Click to copy"} closeDelay={0}>
      <div
        onClick={handleCopy}
        className="relative flex items-center gap-2 rounded-2xl bg-zinc-900 p-1 px-4 cursor-pointer hover:bg-zinc-800/80 transition-colors"
      >
        <code className="flex-1 text-sm text-primary">{code}</code>
        <CopyButton textToCopy={code} copied={copied} onCopy={handleCopy} />
      </div>
    </Tooltip>
  );
}

function InstallTab({
  code,
  hint,
  skipInitHint,
}: {
  code: string;
  hint: string;
  skipInitHint?: boolean;
}) {
  return (
    <div className="flex flex-col items-center space-y-4 py-1">
      <CodeBlock code={code} />
      <p className="text-sm text-zinc-400 text-center">
        {skipInitHint ? (
          hint
        ) : (
          <>
            After installation, run <InlineCode>gaia init</InlineCode> {hint}
          </>
        )}
      </p>
    </div>
  );
}

const installMethods = [
  {
    key: "npm",
    title: "npm",
    code: "npm install -g @heygaia/cli",
    hint: "from any directory.",
  },
  {
    key: "pnpm",
    title: "pnpm",
    code: "pnpm add -g @heygaia/cli",
    hint: "from any directory.",
  },
  {
    key: "bun",
    title: "bun",
    code: "bun add -g @heygaia/cli",
    hint: "from any directory.",
  },
];

const commands = [
  {
    command: "gaia init",
    description: CLI_COMMAND_DESCRIPTIONS.init,
  },
  {
    command: "gaia setup",
    description: CLI_COMMAND_DESCRIPTIONS.setup,
  },
  {
    command: "gaia start",
    description: CLI_COMMAND_DESCRIPTIONS.start,
  },
  {
    command: "gaia dev",
    description: CLI_COMMAND_DESCRIPTIONS.dev,
  },
  {
    command: "gaia dev full",
    description: "Run developer mode + workers in Nx TUI",
  },
  {
    command: "gaia logs",
    description: CLI_COMMAND_DESCRIPTIONS.logs,
  },
  {
    command: "gaia stop",
    description: CLI_COMMAND_DESCRIPTIONS.stop,
  },
  {
    command: "gaia stop --force-ports",
    description: "Aggressively stop listeners on app ports",
  },
  {
    command: "gaia status",
    description: CLI_COMMAND_DESCRIPTIONS.status,
  },
  {
    command: "gaia --version",
    description: "Show the current CLI version",
  },
  {
    command: "gaia --help",
    description: "Display help and all available commands",
  },
];

export function InstallPageClient() {
  return (
    <div className="relative flex min-h-screen w-full flex-col items-center">
      <div
        className={`relative aspect-video w-full overflow-hidden rounded-4xl bg-zinc-900 max-w-4xl mx-auto mt-24 sm:mt-32`}
      >
        <ProgressiveImage
          webpSrc="/images/screenshots/cli.webp"
          pngSrc="/images/screenshots/cli.png"
          alt="Terminal"
          width={1920}
          height={1080}
          className="w-full rounded-4xl"
        />
      </div>

      <section className="relative z-10 flex w-full max-w-5xl flex-col items-center gap-4 px-6 mt-5">
        <h1 className="mt-8 text-4xl font-medium text-white sm:text-7xl font-serif">
          Install GAIA CLI
        </h1>
        <p className="max-w-xl text-center text-lg text-zinc-400">
          Set up your self-hosted GAIA instance with a single command
        </p>
      </section>

      <div className="relative z-10 w-full max-w-5xl space-y-8 pb-6 px-6">
        <div className="flex justify-center mt-8 flex-col">
          <Tabs
            aria-label="Package managers"
            color="primary"
            variant="underlined"
            classNames={{ base: "mx-auto pb-0 mb-0", panel: "pt-3" }}
          >
            {installMethods.map((method) => (
              <Tab key={method.key} title={method.title}>
                <InstallTab
                  code={method.code}
                  hint={method.hint}
                  skipInitHint={"skipInitHint" in method}
                />
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
            href="https://docs.heygaia.io/self-hosting/cli-setup"
            color="primary"
            target="_blank"
            rel="noopener noreferrer"
          >
            Read Full Documentation
          </Button>
          <Button
            as={Link}
            href="https://github.com/heygaia/gaia"
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
