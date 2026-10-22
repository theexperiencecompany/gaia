// @vitest-environment jsdom
import { TOOL_FIXTURES } from "@shared/chat";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RedditIcon } from "@/components/shared/icons";
import RedditSearchCard from "@/features/reddit/components/RedditSearchCard";
import type { RedditData } from "@/types/features/redditTypes";

vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

const redditFixture = TOOL_FIXTURES.find((f) => f.toolName === "reddit_data");

describe("Reddit card header icon", () => {
  it("renders at header size instead of filling the card", () => {
    const data = redditFixture?.data as RedditData;
    if (data.type !== "search")
      throw new Error("reddit_data fixture is not a search");
    render(<RedditSearchCard posts={data.posts} />);

    const icon = screen.getByTitle("Reddit Icon").closest("svg");
    expect(icon?.getAttribute("width")).toBe("20");
    expect(icon?.getAttribute("height")).toBe("20");
  });

  it("has an intrinsic size when the caller passes none", () => {
    render(<RedditIcon />);

    const icon = screen.getByTitle("Reddit Icon").closest("svg");
    expect(icon?.getAttribute("width")).toBe("24");
  });
});
