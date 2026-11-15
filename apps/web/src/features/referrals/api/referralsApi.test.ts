// @vitest-environment jsdom
import type { AxiosAdapter, InternalAxiosRequestConfig } from "axios";
import { AxiosError } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { track } from "@/lib/analytics";
import { apiauth, registerApiErrorHandler } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { processAxiosError } from "@/utils/interceptorUtils";
import { referralsApi } from "./referralsApi";

vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const HTTP_FORBIDDEN = 403;
const HTTP_SERVER_ERROR = 500;

/** The one faked layer: axios's transport answers every request with this envelope. */
const answerWith =
  (status: number, code: string): AxiosAdapter =>
  (config: InternalAxiosRequestConfig) =>
    Promise.reject(
      new AxiosError(
        `Request failed with status code ${status}`,
        AxiosError.ERR_BAD_REQUEST,
        config,
        undefined,
        {
          status,
          statusText: "",
          data: { message: "Refused", code },
          headers: { "content-type": "application/json" },
          config,
        },
      ),
    );

type ReferralCall = () => Promise<unknown>;

const getMe: ReferralCall = referralsApi.getMe;
const getSuggestions: ReferralCall = referralsApi.getSuggestions;
const claimWeeklyCard: ReferralCall = referralsApi.claimWeeklyCard;
const sendInvite: ReferralCall = () =>
  referralsApi.sendInvites(["friend@example.com"], "page");

describe("referralsApi failure reporting", () => {
  const originalAdapter = apiauth.defaults.adapter;
  let ejectAppShellHandler: () => void;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    ejectAppShellHandler = registerApiErrorHandler((error) =>
      processAxiosError(error, { router: { push: vi.fn() } as never }),
    );
  });

  afterEach(() => {
    ejectAppShellHandler();
    apiauth.defaults.adapter = originalAdapter;
    vi.restoreAllMocks();
  });

  it.each<[string, string, ReferralCall]>([
    ["getMe", "REFERRAL_SUBSCRIPTION_REQUIRED", getMe],
    ["getMe", "REFERRALS_DISABLED", getMe],
    ["getSuggestions", "REFERRALS_DISABLED", getSuggestions],
    ["claimWeeklyCard", "REFERRAL_SUBSCRIPTION_REQUIRED", claimWeeklyCard],
    ["claimWeeklyCard", "REFERRALS_DISABLED", claimWeeklyCard],
  ])(
    "%s answers %s without logging, tracking or toasting a failure",
    async (_name, code, call) => {
      apiauth.defaults.adapter = answerWith(HTTP_FORBIDDEN, code);

      await expect(call()).rejects.toMatchObject({
        status: HTTP_FORBIDDEN,
        code,
      });

      expect(console.error).not.toHaveBeenCalled();
      expect(track).not.toHaveBeenCalled();
      expect(toast.error).not.toHaveBeenCalled();
    },
  );

  // An invite is a click, so the paused-program toast is the user's only answer.
  it.each<[string, number, string, ReferralCall]>([
    ["getMe", HTTP_FORBIDDEN, "FORBIDDEN", getMe],
    ["getMe", HTTP_SERVER_ERROR, "internal_error", getMe],
    ["sendInvites", HTTP_FORBIDDEN, "REFERRALS_DISABLED", sendInvite],
  ])(
    "%s still reports a %i %s as a failure",
    async (_name, status, code, call) => {
      apiauth.defaults.adapter = answerWith(status, code);

      await expect(call()).rejects.toMatchObject({ status, code });

      expect(console.error).toHaveBeenCalledTimes(1);
      expect(track).toHaveBeenCalledWith(
        "api:request_failed",
        expect.objectContaining({ status, error_code: code }),
      );
      expect(toast.error).toHaveBeenCalledTimes(1);
    },
  );
});
