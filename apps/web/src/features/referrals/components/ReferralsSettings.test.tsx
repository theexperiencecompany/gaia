// @vitest-environment jsdom
/** The Sent with GAIA opt-out stays reachable whatever the referral overview request did. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReferralMeState } from "../hooks/useReferrals";

const referralMe = vi.fn<() => ReferralMeState>();

vi.mock("../hooks/useReferrals", () => ({
  useReferralMe: () => referralMe(),
  useReferralSuggestions: () => ({ data: [] }),
  sendReferralInvite: vi.fn(),
}));

vi.mock("../hooks/useSentWithGaia", () => ({
  useSentWithGaia: () => ({
    isEnabled: true,
    isSaving: false,
    setEnabled: vi.fn(),
  }),
}));

import { SENT_WITH_GAIA_COPY } from "../referralCopy";
import { ReferralsSettings } from "./ReferralsSettings";

describe("ReferralsSettings", () => {
  it.each<ReferralMeState>([
    { status: "error", retry: vi.fn() },
    { status: "loading" },
    { status: "subscribe_first" },
  ])(
    "keeps the Sent with GAIA toggle while the overview is $status",
    (state) => {
      referralMe.mockReturnValue(state);

      render(<ReferralsSettings />);

      expect(
        screen.getByRole("switch", { name: SENT_WITH_GAIA_COPY.title }),
      ).toBeDefined();
    },
  );
});
