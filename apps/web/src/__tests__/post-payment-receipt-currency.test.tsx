// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/image", () => ({
  default: () => null,
}));

import { PostPaymentReceipt } from "@/features/pricing/components/PostPaymentReceipt";

/** $20.00, in the minor units Dodo charges in. */
const AMOUNT = 2000;

describe("PostPaymentReceipt money formatting", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("prints the charged currency", () => {
    render(
      <PostPaymentReceipt stage="complete" amount={AMOUNT} currency="EUR" />,
    );

    expect(screen.getAllByText("€20.00").length).toBeGreaterThan(0);
    expect(console.error).not.toHaveBeenCalled();
  });

  it("says so when the currency the webhook sent is not a currency", () => {
    // A malformed currency code used to throw out of Intl and get swallowed
    // silently — it must not crash the payment screen, just stop being silent.
    render(
      <PostPaymentReceipt stage="complete" amount={AMOUNT} currency="US$" />,
    );

    expect(console.error).toHaveBeenCalled();
  });

  it("still prints the amount when the currency is unusable", () => {
    render(
      <PostPaymentReceipt stage="complete" amount={AMOUNT} currency="US$" />,
    );

    expect(screen.getAllByText("20 US$").length).toBeGreaterThan(0);
  });
});
