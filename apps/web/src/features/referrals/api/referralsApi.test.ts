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

describe("referralsApi.getMe failure reporting", () => {
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

  it.each(["REFERRAL_SUBSCRIPTION_REQUIRED", "REFERRALS_DISABLED"])(
    "answers %s without logging, tracking or toasting a failure",
    async (code) => {
      apiauth.defaults.adapter = answerWith(HTTP_FORBIDDEN, code);

      await expect(referralsApi.getMe()).rejects.toMatchObject({
        status: HTTP_FORBIDDEN,
        code,
      });

      expect(console.error).not.toHaveBeenCalled();
      expect(track).not.toHaveBeenCalled();
      expect(toast.error).not.toHaveBeenCalled();
    },
  );

  it.each([
    [HTTP_FORBIDDEN, "FORBIDDEN"],
    [HTTP_SERVER_ERROR, "internal_error"],
  ])("still reports a %i %s as a failure", async (status, code) => {
    apiauth.defaults.adapter = answerWith(status, code);

    await expect(referralsApi.getMe()).rejects.toMatchObject({ status, code });

    expect(console.error).toHaveBeenCalledTimes(1);
    expect(track).toHaveBeenCalledWith(
      "api:request_failed",
      expect.objectContaining({ status, error_code: code }),
    );
    expect(toast.error).toHaveBeenCalledTimes(1);
  });
});
