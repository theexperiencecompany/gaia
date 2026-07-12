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

export function DeviceSetupGuide() {
  return (
    <ol className="flex flex-col gap-4">
      {SETUP_STEPS.map((step, index) => (
        <li key={step.title} className="flex gap-3">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-xs font-medium text-zinc-400">
            {index + 1}
          </span>
          <div className="flex flex-col gap-2">
            <div>
              <p className="text-sm font-medium">{step.title}</p>
              <p className="text-sm text-zinc-400">{step.description}</p>
            </div>
            {step.command && (
              <code className="rounded-2xl bg-zinc-900 px-3 py-2 font-mono text-sm text-zinc-300">
                {step.command}
              </code>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
