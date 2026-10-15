/** Who the setup wizard opens for: a fresh instance, or its admin until they finish or skip it. */

import { describe, expect, it } from "vitest";
import type { SetupStatus } from "@/features/settings/api/providersApi";
import {
  opensSetupWizard,
  setupWizardOwed,
} from "@/features/setup-wizard/utils/setupWizardRoute";

function status(overrides: Partial<SetupStatus>): SetupStatus {
  return {
    auth_mode: "local",
    has_admin_account: true,
    registration_policy: "invite_only",
    needs_setup: true,
    wizard_dismissed: false,
    deployment: {
      kind: "selfhost",
      bills: false,
      local_code_sandbox: false,
      blob_store: "local",
      gaia_support: false,
      instance_toolkits: true,
      private_network_endpoints: true,
    },
    providers: {},
    features: {},
    plans_seeded: false,
    bots: {
      telegram_username: null,
      discord_client_id: null,
      slack_workspace_url: null,
    },
    ...overrides,
  };
}

describe("opensSetupWizard", () => {
  it("opens for anyone while the instance has no admin", () => {
    const fresh = status({ has_admin_account: false });

    expect(opensSetupWizard(fresh, undefined)).toBe(true);
    expect(opensSetupWizard(fresh, "member")).toBe(true);
  });

  it("opens for the admin while no AI provider is set up", () => {
    expect(opensSetupWizard(status({}), "admin")).toBe(true);
  });

  it("never opens for a member, who could not save anything", () => {
    expect(opensSetupWizard(status({}), "member")).toBe(false);
  });

  it("stays closed once the admin skipped it", () => {
    expect(opensSetupWizard(status({ wizard_dismissed: true }), "admin")).toBe(
      false,
    );
  });

  it("stays closed once an AI provider works", () => {
    expect(opensSetupWizard(status({ needs_setup: false }), "admin")).toBe(
      false,
    );
  });

  it("does not open for an unknown visitor on an instance with an admin", () => {
    expect(opensSetupWizard(status({}), undefined)).toBe(false);
  });

  it("never opens under WorkOS, where nobody may administer the instance", () => {
    const workos = status({ auth_mode: "workos", has_admin_account: false });

    expect(opensSetupWizard(workos, "admin")).toBe(false);
  });
});

describe("setupWizardOwed", () => {
  it("is owed to the admin until they finish or skip it", () => {
    expect(setupWizardOwed(status({}))).toBe(true);
    expect(setupWizardOwed(status({ wizard_dismissed: true }))).toBe(false);
    expect(setupWizardOwed(status({ needs_setup: false }))).toBe(false);
  });

  it("is owed while no admin exists, even after a dismissal", () => {
    expect(
      setupWizardOwed(
        status({ has_admin_account: false, wizard_dismissed: true }),
      ),
    ).toBe(true);
  });
});
