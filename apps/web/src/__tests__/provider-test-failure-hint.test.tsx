// @vitest-environment jsdom
/** A failed provider test's recovery hint comes from the API's failure code, never from sniffing its prose. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ProviderTestResult } from "@/features/settings/api/providersApi";
import { ProviderTestResultNotice } from "@/features/settings/components/providers/ProviderTestResultNotice";

const KEY_URL = "https://keys.example/new";

const failed = (
  failure: ProviderTestResult["failure"],
  detail = "Provider said no",
): ProviderTestResult => ({ ok: false, detail, failure, models: [] });

describe("ProviderTestResultNotice", () => {
  it("points a rejected key at where keys are issued", () => {
    render(
      <ProviderTestResultNotice
        result={failed("auth_rejected")}
        keyUrl={KEY_URL}
      />,
    );

    expect(
      screen.getByText(new RegExp(`Check your API key at ${KEY_URL}`)),
    ).toBeTruthy();
  });

  it("explains a rate limit and a timeout", () => {
    const { rerender } = render(
      <ProviderTestResultNotice
        result={failed("rate_limited")}
        keyUrl={null}
      />,
    );
    expect(screen.getByText(/Rate limited/)).toBeTruthy();

    rerender(
      <ProviderTestResultNotice result={failed("timeout")} keyUrl={null} />,
    );
    expect(screen.getByText(/didn't respond/)).toBeTruthy();
  });

  it("adds no hint when the detail merely reads like one", () => {
    render(
      <ProviderTestResultNotice
        result={failed("refused", "Invalid model: 401 rate timeout")}
        keyUrl={KEY_URL}
      />,
    );

    expect(screen.queryByText(/Check your API key/)).toBeNull();
    expect(screen.queryByText(/Rate limited/)).toBeNull();
    expect(screen.queryByText(/didn't respond/)).toBeNull();
  });
});
