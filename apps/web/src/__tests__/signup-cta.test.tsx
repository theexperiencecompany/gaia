// @vitest-environment jsdom
/** Every sign-up CTA goes straight to WorkOS on hosted GAIA and to /signup on a self-hosted build. */

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  signupCtaDestination,
  signupCtaHref,
  WORKOS_SIGNUP_URL,
} from "@/features/auth/utils/signupCta";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";

vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("signup CTA", () => {
  it("is the WorkOS sign-up URL on hosted", () => {
    expect(signupCtaHref()).toBe(WORKOS_SIGNUP_URL);
    expect(WORKOS_SIGNUP_URL).toBe(
      "http://localhost:8000/oauth/login/workos?screen_hint=sign-up",
    );
    expect(signupCtaDestination()).toBe("workos_oauth");
  });

  it("is /signup on self-host, which renders local auth", () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
    expect(signupCtaHref()).toBe("/signup");
    expect(signupCtaDestination()).toBe("/signup");
  });

  it("is what GetStartedButton links to by default", () => {
    render(<GetStartedButton />);
    expect(screen.getByRole("link").getAttribute("href")).toBe(
      WORKOS_SIGNUP_URL,
    );
  });
});
