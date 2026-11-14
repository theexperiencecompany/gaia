// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { renderToString } from "react-dom/server";
import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: false }),
}));
vi.mock("@/features/chat/components/interface/RichContentRenderer", () => ({
  RichContentRenderer: ({ content }: { content: string }) => <p>{content}</p>,
}));
vi.mock("@/features/chat/components/interface/MarkdownRenderer", () => ({
  default: ({ content }: { content: string }) => <pre>{content}</pre>,
}));

const CONTENT_URL = "https://c0ntent.gaiausercontent.test/?t=signed";
const issueLinkContentUrl = vi.hoisted(() => vi.fn());
vi.mock("@/features/short-links/api/linkViewerApi", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/short-links/api/linkViewerApi")
  >()),
  issueLinkContentUrl,
}));

import { LinkUnavailable } from "@/features/short-links/components/LinkUnavailable";
import { PublicSessionArtifactView } from "@/features/short-links/components/PublicSessionArtifactView";
import { PublicWorkflowRunView } from "@/features/short-links/components/PublicWorkflowRunView";
import { DEAD_LINK_COPY } from "@/features/short-links/constants";
import { LINK_VIEWS } from "@/features/short-links/registry";
import type { DeadLinkDenial } from "@/features/short-links/types";
import type {
  LinkContent,
  PublicSessionArtifact,
  PublicWorkflowRun,
} from "@/types/features/shortLinkTypes";

const RUN: PublicWorkflowRun = {
  target_type: "workflow_run",
  workflow_title: "Morning digest",
  status: "success",
  started_at: "2026-11-10T06:27:00Z",
  completed_at: "2026-11-10T06:28:00Z",
  summary: "Done",
};

function withLocale(children: ReactNode) {
  return (
    <NextIntlClientProvider locale="en" messages={{}}>
      {children}
    </NextIntlClientProvider>
  );
}

describe("LINK_VIEWS", () => {
  it("has a view for every target type the API can link to", () => {
    const openapi = JSON.parse(
      readFileSync(
        path.resolve(__dirname, "../../../api/openapi.json"),
        "utf8",
      ),
    ) as { components: { schemas: Record<string, { enum: string[] }> } };
    const targetTypes = openapi.components.schemas.ShortLinkTargetType.enum;

    expect(Object.keys(LINK_VIEWS).sort()).toEqual([...targetTypes].sort());
  });
});

describe("a heygaia.link that doesn't open", () => {
  it.each([
    ["link_not_found", "This link doesn't exist."],
    [
      "link_revoked",
      "This link was turned off by the person who shared it. Ask them for a new one.",
    ],
    [
      "link_expired",
      "This link has expired. Ask the person who shared it for a new one.",
    ],
    ["link_target_deleted", "What this link pointed to was deleted."],
    ["link_removed", "This link was removed for breaking GAIA's terms."],
  ] satisfies [DeadLinkDenial, string][])(
    "%s says so and leads to GAIA",
    (denial, copy) => {
      render(<LinkUnavailable state={{ denial }} />);

      expect(screen.getByRole("heading", { name: copy })).toBeTruthy();
      expect(
        screen.getByRole("button", { name: "Go to GAIA" }).getAttribute("href"),
      ).toBe("/");
    },
  );

  it("covers every dead denial with copy", () => {
    expect(Object.keys(DEAD_LINK_COPY).sort()).toEqual(
      [
        "link_expired",
        "link_lookup_locked",
        "link_not_found",
        "link_removed",
        "link_revoked",
        "link_target_deleted",
      ].sort(),
    );
  });

  it("asks a signed-out viewer to sign in and come back to the link", () => {
    render(
      <LinkUnavailable
        state={{ denial: "link_sign_in_required", slug: "abcdefghijk" }}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Sign in to open this" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Sign in" }).getAttribute("href"),
    ).toBe("/login?return_url=%2Fl%2Fabcdefghijk");
  });

  it("tells a signed-in viewer who isn't a grantee which account they're using", () => {
    render(
      <LinkUnavailable
        state={{ denial: "link_forbidden", signedInAs: "sam@example.com" }}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "You don't have access to this." }),
    ).toBeTruthy();
    expect(
      screen.getByText("You're signed in as sam@example.com."),
    ).toBeTruthy();
  });
});

describe("a shared workflow run", () => {
  const originalTz = process.env.TZ;
  beforeAll(() => {
    process.env.TZ = "Asia/Kolkata";
  });
  afterAll(() => {
    process.env.TZ = originalTz;
  });

  it("shows when it ran in the reader's own time zone", () => {
    render(withLocale(<PublicWorkflowRunView view={RUN} />));

    const time = document.querySelector("time");
    expect(time?.textContent).toContain("11:57");
    expect(time?.textContent).not.toContain("UTC");
  });

  it("server-renders the run's date, with no clock time to disagree with the reader's", () => {
    const html = renderToString(
      withLocale(<PublicWorkflowRunView view={RUN} />),
    );

    expect(html).toMatch(
      /<time dateTime="2026-11-10T06:27:00Z"[^>]*>Nov 10, 2026<\/time>/,
    );
  });
});

describe("a shared file", () => {
  const FILE: PublicSessionArtifact = {
    target_type: "session_artifact",
    filename: "report.html",
    content_type: "text/html",
    size_bytes: 2048,
    text: null,
  };

  beforeEach(() => {
    issueLinkContentUrl.mockReset();
  });

  function content(render: LinkContent["render"], mime: string): LinkContent {
    return { content_id: "c0ntent", mime, size_bytes: 2048, render };
  }

  function renderFile(
    view: PublicSessionArtifact,
    linkContent: LinkContent | null,
    downloadable = true,
  ) {
    issueLinkContentUrl.mockResolvedValue({
      content_url: CONTENT_URL,
      expires_at: new Date(Date.now() + 600_000).toISOString(),
    });
    return render(
      <PublicSessionArtifactView
        slug="abcdefghijk"
        view={view}
        content={linkContent}
        downloadable={downloadable}
        reportAction={<span>report</span>}
      />,
    );
  }

  it("runs active HTML only in a sandbox with no same-origin and no top navigation", async () => {
    const { container } = renderFile(
      FILE,
      content("frame_active", "text/html"),
    );

    await waitFor(() => expect(container.querySelector("iframe")).toBeTruthy());
    const frame = container.querySelector("iframe");
    expect(frame?.getAttribute("src")).toBe(CONTENT_URL);
    expect(frame?.getAttribute("sandbox")).toBe(
      "allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-downloads",
    );
    expect(frame?.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame?.getAttribute("allow")).toBe("");
    expect(frame?.getAttribute("loading")).toBe("lazy");
    expect(frame?.hasAttribute("srcdoc")).toBe(false);
    expect(issueLinkContentUrl).toHaveBeenCalledWith("abcdefghijk");
  });

  it.each([
    ["image", "image/png"],
    ["image_svg", "image/svg+xml"],
  ] as const)(
    "shows a %s through an img, never a frame",
    async (mode, mime) => {
      const { container } = renderFile(
        { ...FILE, filename: "chart", content_type: mime },
        content(mode, mime),
      );

      await waitFor(() => expect(container.querySelector("img")).toBeTruthy());
      expect(container.querySelector("img")?.getAttribute("src")).toBe(
        CONTENT_URL,
      );
      expect(container.querySelector("iframe")).toBeNull();
    },
  );

  it.each([
    ["video/mp4", "video"],
    ["audio/mpeg", "audio"],
  ])("plays %s media in a %s element", async (mime, tag) => {
    const { container } = renderFile(
      { ...FILE, filename: "clip", content_type: mime },
      content("media", mime),
    );

    await waitFor(() => expect(container.querySelector(tag)).toBeTruthy());
    expect(container.querySelector(tag)?.getAttribute("src")).toBe(CONTENT_URL);
  });

  it("frames a PDF unsandboxed, with Open navigating the tab to it", async () => {
    const { container } = renderFile(
      { ...FILE, filename: "report.pdf", content_type: "application/pdf" },
      content("pdf", "application/pdf"),
    );

    await waitFor(() => expect(container.querySelector("iframe")).toBeTruthy());
    const frame = container.querySelector("iframe");
    expect(frame?.getAttribute("src")).toBe(CONTENT_URL);
    expect(frame?.hasAttribute("sandbox")).toBe(false);
    const open = screen.getByRole("button", { name: "Open" });
    expect(open.getAttribute("href")).toBe(CONTENT_URL);
    expect(open.getAttribute("target")).toBeNull();
  });

  it("shows HTML it renders itself as source, never as a srcDoc frame", () => {
    const { container } = renderFile(
      { ...FILE, text: "<script>alert(1)</script>" },
      null,
    );

    expect(container.querySelector("iframe")).toBeNull();
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeTruthy();
    expect(issueLinkContentUrl).not.toHaveBeenCalled();
  });

  it("describes a file it can only download, under a bar that downloads from the API", () => {
    const { container } = renderFile(
      { ...FILE, filename: "data.zip", content_type: "application/zip" },
      null,
    );

    expect(container.querySelector("iframe")).toBeNull();
    expect(screen.getByText(/Download it to open it/)).toBeTruthy();
    expect(screen.getByText("Made with GAIA")).toBeTruthy();
    expect(screen.getByText("report")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Download" }).getAttribute("href"),
    ).toBe("http://localhost:8000/l/abcdefghijk/download");
  });

  it("offers no Download when the link may not serve the file's bytes", () => {
    renderFile(
      { ...FILE, filename: "huge.zip", content_type: "application/zip" },
      null,
      false,
    );

    expect(screen.queryByRole("button", { name: "Download" })).toBeNull();
    expect(screen.queryByText(/Download it to open it/)).toBeNull();
    expect(screen.getByText("report")).toBeTruthy();
  });
});
