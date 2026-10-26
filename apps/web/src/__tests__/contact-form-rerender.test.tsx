// @vitest-environment jsdom
/** Regression: a re-render of /contact's form looped forever (React #301) because its preset was a fresh object each render. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import ContactForm from "@/features/contact/components/ContactForm";
import { useContactSupport } from "@/features/support/hooks/useContactSupport";

function withQueryClient(node: ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>
  );
}

describe("contact form", () => {
  it("survives a re-render with the same preset", () => {
    const { rerender } = render(
      withQueryClient(<ContactForm initialType="support" initialTitle="Hi" />),
    );

    rerender(
      withQueryClient(<ContactForm initialType="support" initialTitle="Hi" />),
    );

    expect(screen.getByDisplayValue("Hi")).toBeTruthy();
  });
});

describe("useContactSupport", () => {
  it("keeps the user's edits when the preset is an equal fresh object", () => {
    const { result, rerender } = renderHook(
      (preset: { title: string }) => useContactSupport(preset),
      { initialProps: { title: "Hi" } },
    );

    act(() => result.current.handleInputChange("title", "Edited"));
    rerender({ title: "Hi" });

    expect(result.current.formData.title).toBe("Edited");
  });

  it("resets the user's edits when the preset changes", () => {
    const { result, rerender } = renderHook(
      (preset: { title: string }) => useContactSupport(preset),
      { initialProps: { title: "Hi" } },
    );

    act(() => result.current.handleInputChange("title", "Edited"));
    rerender({ title: "Another preset" });

    expect(result.current.formData.title).toBe("Another preset");
  });
});
