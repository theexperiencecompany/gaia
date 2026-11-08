// @vitest-environment jsdom
/** Finishing the wizard with no chat provider says so once, with one way to fix it. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("next/dynamic", () => ({ default: () => () => null }));

import { PROVIDERS_SETTINGS_PATH } from "@/features/settings/components/providers/providerRows";
import { DoneStep } from "@/features/setup-wizard/components/steps/DoneStep";

const CATALOG = {
  llm_provider_keys: ["openai"],
  providers: {},
  custom_presets: {},
  features: {},
} as unknown as ProviderCatalog;

const STATUS = {
  auth_mode: "local",
  has_admin_account: true,
  providers: { openai: { configured: false, env_shadowed: false } },
  features: {},
} as unknown as SetupStatus;

describe("DoneStep without a chat provider", () => {
  it("says chat needs a provider once and links to Settings once", () => {
    const { container } = render(
      <DoneStep status={STATUS} catalog={CATALOG} />,
    );

    expect(screen.getAllByText(/Chat requires a provider/)).toHaveLength(1);
    expect(
      container.querySelectorAll(`a[href="${PROVIDERS_SETTINGS_PATH}"]`),
    ).toHaveLength(1);
  });
});
