import type { DeviceResponse } from "@shared/api/generated";

export type Device = DeviceResponse;

/**
 * The `device_onboarding_required` chat payload asks the user to install the
 * bridge CLI and pair a machine before reaching a local MCP server — purely
 * instructional, never runs or POSTs anything itself. `install_commands` is
 * keyed by package manager, mirroring CLI_INSTALL_COMMANDS in
 * `@shared/cli/command-manifest`.
 */
export interface DeviceOnboardingRequiredData {
  install_commands: {
    npm: string;
    pnpm: string;
    bun: string;
  };
  docs_url: string;
  pair_command: string;
  up_command: string;
  message: string;
}

/**
 * The `device_approval_required` chat payload — a machine is waiting on a
 * pairing code. The card is presentational: it shows the code and routes the
 * user to the existing authenticated approve page (`approve_url`), which owns
 * the actual approval POST.
 */
export interface DeviceApprovalRequiredData {
  approve_url: string;
  code: string;
  message: string;
}
