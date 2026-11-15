// @vitest-environment jsdom
/** A deep link to Settings > Referrals while the program is off leaves the page instead of rendering any of it. */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReferralMeState } from "@/features/referrals/hooks/useReferrals";

const redirect = vi.fn((path: string) => {
  throw new Error(`redirected to ${path}`);
});
const referralMe = vi.fn<() => ReferralMeState>();

vi.mock("next/navigation", () => ({
  redirect: (path: string) => redirect(path),
  RedirectType: { replace: "replace" },
}));
vi.mock("@/features/referrals/hooks/useReferrals", () => ({
  useReferralMe: () => referralMe(),
}));
vi.mock("@/features/settings/hooks/useSetupStatus", () => ({
  useDeployment: () => ({ bills: true }),
}));
vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ userId: "user-1", role: undefined }),
}));
vi.mock("@/features/settings/config/sectionComponents", () => ({
  SectionComponent: ({ section }: { section: string }) => (
    <p>section {section}</p>
  ),
}));
vi.mock("@/components/shared/ConfirmActionDialog", () => ({
  ConfirmActionDialog: () => null,
}));

import SettingsSectionClient from "@/app/[locale]/(main)/settings/[section]/SettingsSectionClient";

afterEach(() => {
  cleanup();
  redirect.mockClear();
});

describe("Settings > Referrals", () => {
  it("redirects to the default section while referrals are off", () => {
    referralMe.mockReturnValue({ status: "disabled" });

    expect(() => render(<SettingsSectionClient section="referrals" />)).toThrow(
      "redirected to /settings/account",
    );
    expect(screen.queryByText("section referrals")).toBeNull();
  });

  it("renders the section while referrals are on", () => {
    referralMe.mockReturnValue({ status: "loading" });

    render(<SettingsSectionClient section="referrals" />);

    expect(screen.getByText("section referrals")).toBeDefined();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("leaves other sections alone while referrals are off", () => {
    referralMe.mockReturnValue({ status: "disabled" });

    render(<SettingsSectionClient section="account" />);

    expect(screen.getByText("section account")).toBeDefined();
  });
});
