import type { SetupStatusResponse } from "@shared/api/generated";
import { describe, expect, it } from "vitest";

import { getLocalAuthError } from "@/features/auth/api/authApi";
import { resolveSignupMode } from "@/features/auth/utils/signupMode";
import { isSettingsSectionAllowed } from "@/features/settings/config/settingsConfig";

const status = (
  overrides: Partial<SetupStatusResponse>,
): SetupStatusResponse => ({
  auth_mode: "local",
  billing_enabled: false,
  has_admin_account: true,
  registration_policy: "invite_only",
  needs_setup: false,
  plans_seeded: true,
  providers: {},
  ...overrides,
});

describe("resolveSignupMode", () => {
  it("offers the first account before an admin exists, invite or not", () => {
    const fresh = status({ has_admin_account: false });
    expect(resolveSignupMode(fresh, undefined)).toBe("first_account");
    expect(resolveSignupMode(fresh, "tok")).toBe("first_account");
  });

  it("is closed on an invite-only instance without an invite", () => {
    expect(resolveSignupMode(status({}), undefined)).toBe("closed");
    expect(resolveSignupMode(status({}), "")).toBe("closed");
  });

  it("admits a member with an invite or when sign-up is open", () => {
    expect(resolveSignupMode(status({}), "tok")).toBe("member");
    expect(
      resolveSignupMode(status({ registration_policy: "open" }), undefined),
    ).toBe("member");
  });

  it("leaves the decision to the API when the status is unreadable", () => {
    expect(resolveSignupMode(null, undefined)).toBe("unknown");
  });
});

describe("isSettingsSectionAllowed", () => {
  it("shows Members to the admin only", () => {
    expect(isSettingsSectionAllowed("members", "admin")).toBe(true);
    expect(isSettingsSectionAllowed("members", "member")).toBe(false);
    expect(isSettingsSectionAllowed("members", undefined)).toBe(false);
  });

  it("hides the instance's AI provider keys from members only", () => {
    expect(isSettingsSectionAllowed("providers", "member")).toBe(false);
    expect(isSettingsSectionAllowed("providers", "admin")).toBe(true);
    expect(isSettingsSectionAllowed("providers", undefined)).toBe(true);
  });

  it("leaves personal sections open to everyone", () => {
    expect(isSettingsSectionAllowed("account", "member")).toBe(true);
  });
});

describe("getLocalAuthError", () => {
  it("reads the code and message from the API's error envelope", () => {
    const error = {
      response: {
        status: 403,
        data: { code: "registration_closed", message: "Closed" },
      },
    };
    expect(getLocalAuthError(error)).toEqual({
      status: 403,
      errorCode: "registration_closed",
      message: "Closed",
    });
  });

  it("returns only the status for a body that is not an envelope", () => {
    const error = { response: { status: 502, data: "<html>" } };
    expect(getLocalAuthError(error)).toEqual({
      status: 502,
      errorCode: undefined,
      message: undefined,
    });
  });
});
