// @vitest-environment jsdom
/** The public /contact form: a visitor gives an email and passes Turnstile; a signed-in user keeps the session route. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { forwardRef, type ReactNode, useImperativeHandle } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ContactForm from "@/features/contact/components/ContactForm";
import { CONTACT_FORM_MESSAGES } from "@/features/contact/constants";

const mocks = vi.hoisted(() => ({
  currentUserEmail: "",
  getResponsePromise: vi.fn<() => Promise<string>>(),
  reset: vi.fn(),
  submitRequest: vi.fn(),
  submitPublicRequest: vi.fn(),
}));

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ email: mocks.currentUserEmail }),
}));

vi.mock("@/features/contact/constants", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/contact/constants")>()),
  // Cloudflare's documented always-pass test site key.
  TURNSTILE_SITE_KEY: "1x00000000000000000000AA",
}));

vi.mock("@marsidev/react-turnstile", () => ({
  Turnstile: forwardRef(function FakeTurnstile(_props, ref) {
    useImperativeHandle(ref, () => ({
      getResponsePromise: mocks.getResponsePromise,
      reset: mocks.reset,
    }));
    return <div data-testid="turnstile" />;
  }),
}));

vi.mock("@/features/support/api/supportApi", () => ({
  supportApi: {
    submitRequest: mocks.submitRequest,
    submitPublicRequest: mocks.submitPublicRequest,
  },
}));

const TITLE = "Cannot sign in";
const DESCRIPTION = "The login page loops forever after I click continue";
const ACCEPTED = { success: true, message: "ok", ticket_id: "GAIA-1" };

function renderForm() {
  const node: ReactNode = (
    <QueryClientProvider client={new QueryClient()}>
      <ContactForm
        initialType="support"
        initialTitle={TITLE}
        initialDescription={DESCRIPTION}
        data-testid="contact-form"
      />
    </QueryClientProvider>
  );
  return render(node);
}

// requestSubmit, not a bare submit event: it runs the browser's constraint validation like a real click.
const submit = () =>
  act(() =>
    (screen.getByTestId("contact-form") as HTMLFormElement).requestSubmit(),
  );
const emailInput = () => screen.getByLabelText(/email/i);

beforeEach(() => {
  mocks.currentUserEmail = "";
  mocks.getResponsePromise.mockResolvedValue("turnstile-token");
  mocks.submitRequest.mockResolvedValue(ACCEPTED);
  mocks.submitPublicRequest.mockResolvedValue(ACCEPTED);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("contact form for a visitor", () => {
  it("asks for an email and submits it with the Turnstile token to the public route", async () => {
    renderForm();
    expect(screen.getByTestId("turnstile")).toBeTruthy();

    fireEvent.change(emailInput(), {
      target: { value: "visitor@example.com" },
    });
    submit();

    await waitFor(() => expect(mocks.submitPublicRequest).toHaveBeenCalled());
    expect(mocks.submitPublicRequest).toHaveBeenCalledWith({
      type: "support",
      title: TITLE,
      description: DESCRIPTION,
      email: "visitor@example.com",
      name: null,
      turnstile_token: "turnstile-token",
    });
    expect(mocks.submitRequest).not.toHaveBeenCalled();
    await waitFor(() => expect(mocks.reset).toHaveBeenCalled());
  });

  it("refuses an invalid email before asking Turnstile", async () => {
    renderForm();

    fireEvent.change(emailInput(), { target: { value: "not-an-email" } });
    submit();

    expect(
      await screen.findByText(CONTACT_FORM_MESSAGES.INVALID_EMAIL),
    ).toBeTruthy();
    expect(mocks.getResponsePromise).not.toHaveBeenCalled();
    expect(mocks.submitPublicRequest).not.toHaveBeenCalled();
  });

  it("shows a verification error and sends nothing when Turnstile fails", async () => {
    mocks.getResponsePromise.mockRejectedValue(new Error("challenge failed"));
    renderForm();

    fireEvent.change(emailInput(), {
      target: { value: "visitor@example.com" },
    });
    submit();

    expect(
      await screen.findByText(CONTACT_FORM_MESSAGES.VERIFICATION_FAILED),
    ).toBeTruthy();
    expect(mocks.submitPublicRequest).not.toHaveBeenCalled();
  });
});

describe("contact form for a signed-in user", () => {
  it("hides the email field and Turnstile and keeps the session route", async () => {
    mocks.currentUserEmail = "me@example.com";
    renderForm();

    expect(screen.queryByLabelText(/email/i)).toBeNull();
    expect(screen.queryByTestId("turnstile")).toBeNull();
    submit();

    await waitFor(() => expect(mocks.submitRequest).toHaveBeenCalled());
    expect(mocks.submitRequest).toHaveBeenCalledWith(
      { type: "support", title: TITLE, description: DESCRIPTION },
      [],
    );
    expect(mocks.submitPublicRequest).not.toHaveBeenCalled();
    expect(mocks.getResponsePromise).not.toHaveBeenCalled();
  });
});
