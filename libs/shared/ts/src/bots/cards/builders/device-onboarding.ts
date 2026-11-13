import type { CLI_INSTALL_COMMANDS } from "../../../cli/command-manifest";
import type { Card } from "../types";

/**
 * The `device_onboarding_required` payload (app/utils/device_onboarding.py):
 * install the CLI, pair a machine, send back the code it prints.
 */
export interface DeviceOnboardingRequiredData {
  /** The install command per package manager. */
  install_commands: Record<keyof typeof CLI_INSTALL_COMMANDS, string>;
  docs_url: string;
  pair_command: string;
  up_command: string;
  message: string;
}

const ONBOARDING_TITLE = "Connect a device";
const SHELL_LANGUAGE = "bash";
const DOCS_LABEL = "Setup guide";
const INSTALL_STEP = "**1. Install the GAIA CLI**";
const PAIR_STEP = "**2. Pair this machine**";
const CODE_STEP =
  "**3. Send me the code it prints**, and I'll give you the link to approve it. Once approved, bring the device online:";

/**
 * The install, pair and approve steps, the way the web card walks them. Install
 * shows npm, the web card's default tab and the command the agent's own copy uses.
 */
export function buildDeviceOnboardingCards(
  data: DeviceOnboardingRequiredData,
): Card[] {
  return [
    {
      title: ONBOARDING_TITLE,
      accent: "brand",
      blocks: [
        { kind: "text", markdown: data.message },
        { kind: "text", markdown: INSTALL_STEP },
        {
          kind: "code",
          code: data.install_commands.npm,
          language: SHELL_LANGUAGE,
        },
        { kind: "text", markdown: PAIR_STEP },
        { kind: "code", code: data.pair_command, language: SHELL_LANGUAGE },
        { kind: "text", markdown: CODE_STEP },
        { kind: "code", code: data.up_command, language: SHELL_LANGUAGE },
      ],
      actions: [{ kind: "link", label: DOCS_LABEL, url: data.docs_url }],
    },
  ];
}
