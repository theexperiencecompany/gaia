// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buttonVariants } from "@/components/ui/button-variants";
import { Skeleton } from "@/components/ui/skeleton";

// v2 never defined shadcn's `accent` colour, so its neutral hover and fill
// classes rendered nothing; in v3 `accent` is HeroUI's brand blue, and the same
// classes flashed #00bbff on every ghost button hover (the chat header).
const BRAND_ACCENT = /(^|:)(bg|text)-accent(-foreground)?(\/\d+)?$/;

const brandAccentClasses = (classes: string) =>
  classes.split(/\s+/).filter((token) => BRAND_ACCENT.test(token));

describe("shadcn's neutral states", () => {
  it.each(["ghost", "outline"] as const)(
    "a %s button takes no brand accent",
    (variant) => {
      expect(brandAccentClasses(buttonVariants({ variant }))).toEqual([]);
    },
  );

  it("a skeleton takes no brand accent", () => {
    const { container } = render(<Skeleton />);
    const skeleton = container.firstElementChild as HTMLElement;
    expect(brandAccentClasses(skeleton.className)).toEqual([]);
  });

  it("the primary button keeps the brand accent", () => {
    expect(
      brandAccentClasses(buttonVariants({ variant: "default" })),
    ).toContain("bg-accent");
  });
});
