"use client";

import { CLI_INSTALL_COMMANDS } from "@shared/cli/command-manifest";
import CopyButton from "@/components/ui/CopyButton";
import { BRIDGE_ADD_COMMAND, BRIDGE_CLI_NAME } from "../constants";

interface SetupStep {
  title: string;
  description: string;
  command?: string;
}

const SETUP_STEPS: SetupStep[] = [
  {
    title: `Install the ${BRIDGE_CLI_NAME} CLI`,
    description: "On the machine you want to connect to GAIA.",
    command: CLI_INSTALL_COMMANDS.npm,
  },
  {
    title: "Start the guided setup",
    description:
      "It pairs this machine with your account, then walks you through exposing a local MCP server or folder.",
    command: BRIDGE_ADD_COMMAND,
  },
  {
    title: "Enter the pairing code",
    description:
      "The CLI prints a short code and waits. Type it below to approve this machine.",
  },
];

function CommandRow({ command }: { command: string }) {
  return (
    <div className="flex items-center gap-2 rounded-xl bg-zinc-900 py-1 pr-1 pl-3">
      <code className="min-w-0 flex-1 truncate font-mono text-xs text-zinc-300">
        {command}
      </code>
      <CopyButton
        textToCopy={command}
        variant="light"
        size="md"
        className="shrink-0 text-zinc-400 data-[hover=true]:text-zinc-100"
      />
    </div>
  );
}

export function DeviceSetupGuide() {
  return (
    <ol className="flex flex-col gap-5">
      {SETUP_STEPS.map((step, index) => (
        <li key={step.title} className="flex gap-3">
          <span className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-[11px] font-medium text-zinc-400 tabular-nums">
            {index + 1}
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <div className="flex flex-col gap-0.5">
              <p className="text-sm font-medium text-zinc-100">{step.title}</p>
              <p className="text-pretty text-sm text-zinc-400">
                {step.description}
              </p>
            </div>
            {step.command && <CommandRow command={step.command} />}
          </div>
        </li>
      ))}
    </ol>
  );
}
