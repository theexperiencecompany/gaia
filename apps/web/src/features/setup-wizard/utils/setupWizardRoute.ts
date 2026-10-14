import type { CurrentUser } from "@/features/auth/utils/toCurrentUser";
import type { SetupStatus } from "@/features/settings/api/providersApi";

/**
 * Whether the instance still owes its admin the wizard: no admin exists yet,
 * or no AI provider works and the admin has not skipped it. Only local auth
 * has an admin who can save anything.
 */
export function setupWizardOwed(status: SetupStatus): boolean {
  if (status.auth_mode !== "local") return false;
  if (!status.has_admin_account) return true;
  return status.needs_setup && !status.wizard_dismissed;
}

/**
 * Whether to send this visitor to /setup. Pass role undefined where it is
 * unknown (the "/" redirect): only a fresh instance then opens the wizard.
 */
export function opensSetupWizard(
  status: SetupStatus,
  role: CurrentUser["role"],
): boolean {
  if (!setupWizardOwed(status)) return false;
  return !status.has_admin_account || role === "admin";
}
