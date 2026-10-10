// @vitest-environment jsdom
//
// A chat link into this app (the API links to `/integrations` with its
// FRONTEND_URL, so the absolute form is what arrives) stays in this tab;
// every other link opens beside the app.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import CustomAnchor from "@/features/chat/components/code-block/CustomAnchor";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>
    {children}
  </QueryClientProvider>
);

const renderedTarget = (href: string) => {
  const { getByRole, unmount } = render(
    <CustomAnchor href={href}>link</CustomAnchor>,
    { wrapper },
  );
  const target = getByRole("link").getAttribute("target");
  unmount();
  return target;
};

describe("CustomAnchor target", () => {
  beforeAll(() => {
    // jsdom has no IntersectionObserver; the anchor only uses it to defer
    // the metadata fetch, which is not under test here.
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        observe() {
          // Never reports intersection: the anchor stays out of view.
        }
        unobserve() {
          // Nothing was observed.
        }
        disconnect() {
          // Nothing was observed.
        }
      },
    );
  });

  it("keeps an app link in this tab", () => {
    expect(renderedTarget(`${window.location.origin}/integrations`)).toBeNull();
    expect(renderedTarget("/integrations")).toBeNull();
  });

  it("opens any other origin beside the app", () => {
    expect(renderedTarget("https://docs.heygaia.io/setup")).toBe("_blank");
  });
});
