// @vitest-environment jsdom

import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Toaster } from "@/components/ui/Toaster";
import { toast } from "@/lib/toast";

const ERROR_MESSAGE = "Couldn't connect Trello. Please try again.";
const SILEO_DEFAULT_DURATION_MS = 6000;

describe("toast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    render(<Toaster />);
  });

  afterEach(() => {
    act(() => toast.clear());
    vi.useRealTimers();
  });

  it("keeps an error that replaces a loading toast visible for its full duration", () => {
    let id = "";
    act(() => {
      id = toast.loading("Connecting to Trello...");
    });
    act(() => {
      toast.error(ERROR_MESSAGE, { id });
    });

    act(() => {
      vi.advanceTimersByTime(SILEO_DEFAULT_DURATION_MS - 1000);
    });

    expect(screen.getByText(ERROR_MESSAGE)).toBeTruthy();
  });
});
