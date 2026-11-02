import type { CaptureResult } from "posthog-js";
import { describe, expect, it } from "vitest";

import { scrubCheckoutReturnParams } from "@/lib/observability/checkout-url-scrub";

/** The exact query Dodo's test mode returned a declined checkout to. */
const RETURN_URL =
  "https://heygaia.io/payment/success?subscription_id=sub_1&payment_id=pay_1&status=failed&email=pat%40example.com";

const pageview = (overrides: Partial<CaptureResult> = {}): CaptureResult => ({
  uuid: "u1",
  event: "$pageview",
  properties: {
    $current_url: RETURN_URL,
    $pathname: "/payment/success",
    $referrer: RETURN_URL.replace("/payment/success", "/onboarding"),
    $host: "heygaia.io",
  },
  ...overrides,
});

describe("scrubCheckoutReturnParams", () => {
  it("takes the email and Dodo's ids out of every URL a pageview carries", () => {
    const sent = scrubCheckoutReturnParams(pageview());

    expect(sent?.properties.$current_url).toBe(
      "https://heygaia.io/payment/success",
    );
    expect(sent?.properties.$referrer).toBe("https://heygaia.io/onboarding");
    expect(sent?.properties.$pathname).toBe("/payment/success");
    expect(JSON.stringify(sent)).not.toContain("example.com");
    expect(JSON.stringify(sent)).not.toContain("pay_1");
  });

  it("scrubs the first-touch person properties the same way", () => {
    const sent = scrubCheckoutReturnParams(
      pageview({
        $set_once: { $initial_current_url: RETURN_URL },
        $set: { $current_url: RETURN_URL },
      }),
    );

    expect(sent?.$set_once?.$initial_current_url).toBe(
      "https://heygaia.io/payment/success",
    );
    expect(sent?.$set?.$current_url).toBe("https://heygaia.io/payment/success");
  });

  it("keeps the rest of the query, and leaves URLs that are not Dodo returns alone", () => {
    const sent = scrubCheckoutReturnParams(
      pageview({
        properties: {
          $current_url: `${RETURN_URL}&ref=newsletter`,
          // `status` alone is an ordinary filter, not a checkout return.
          $referrer: "https://heygaia.io/todos?status=open",
        },
      }),
    );

    expect(sent?.properties.$current_url).toBe(
      "https://heygaia.io/payment/success?ref=newsletter",
    );
    expect(sent?.properties.$referrer).toBe(
      "https://heygaia.io/todos?status=open",
    );
  });

  it("passes a dropped event through as dropped", () => {
    expect(scrubCheckoutReturnParams(null)).toBeNull();
  });
});
