// @vitest-environment jsdom
import { Link } from "@heroui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HeroUIProvider } from "./HeroUIProvider";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

describe("HeroUIProvider", () => {
  beforeEach(() => push.mockClear());

  it("sends an internal HeroUI link through the Next.js router", () => {
    render(
      <HeroUIProvider>
        <Link href="/signup">Sign up</Link>
      </HeroUIProvider>,
    );

    fireEvent.click(screen.getByRole("link", { name: "Sign up" }));

    expect(push).toHaveBeenCalledTimes(1);
    expect(push.mock.calls[0]?.[0]).toBe("/signup");
  });

  it("leaves an external link to the browser", () => {
    render(
      <HeroUIProvider>
        <Link href="https://example.com/docs" target="_blank">
          Docs
        </Link>
      </HeroUIProvider>,
    );

    fireEvent.click(screen.getByRole("link", { name: "Docs" }));

    expect(push).not.toHaveBeenCalled();
  });
});
