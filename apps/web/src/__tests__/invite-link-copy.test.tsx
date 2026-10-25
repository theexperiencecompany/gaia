// @vitest-environment jsdom
/** Invite links on a plain-http self-host (no Clipboard API) must still be copyable. */

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const toast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
}));
vi.mock("@/lib/toast", () => ({ toast }));

import { InviteLinksSection } from "@/features/settings/components/members/InviteLinksSection";

function renderSection() {
  render(
    <InviteLinksSection
      invites={[]}
      onCreate={(onCreated) => onCreated("tok123")}
      isCreating={false}
      onRevoke={vi.fn()}
      revokingInviteId={null}
    />,
  );
}

beforeEach(() => {
  // An insecure context (http://<server-ip>:3000) exposes no Clipboard API.
  vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
  document.execCommand = vi.fn(() => false);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("invite links without the Clipboard API", () => {
  it("creating a link shows it and reports no copy failure", () => {
    renderSection();

    fireEvent.click(screen.getByRole("button", { name: /create link/i }));

    const field = screen.getByLabelText("New invite link") as HTMLInputElement;
    expect(field.value).toContain("/signup?invite=tok123");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("the copy button selects the link for the user instead of failing", async () => {
    renderSection();
    fireEvent.click(screen.getByRole("button", { name: /create link/i }));
    const field = screen.getByLabelText("New invite link") as HTMLInputElement;

    fireEvent.click(screen.getByRole("button", { name: "Copy invite link" }));
    await vi.waitFor(() => expect(toast.info).toHaveBeenCalled());

    expect(toast.error).not.toHaveBeenCalled();
    expect(field.selectionStart).toBe(0);
    expect(field.selectionEnd).toBe(field.value.length);
  });
});
