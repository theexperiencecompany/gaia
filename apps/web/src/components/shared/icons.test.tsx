// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import * as icons from "./icons";

const ICONS = Object.entries(icons).filter(
  (entry): entry is [string, (props: object) => React.JSX.Element] =>
    typeof entry[1] === "function",
);

describe("shared icons are decorative", () => {
  it.each(ICONS)(
    "%s adds nothing to its button's accessible name",
    (_, Icon) => {
      render(
        <button type="button">
          Regenerate
          <Icon />
        </button>,
      );
      expect(screen.getByRole("button", { name: "Regenerate" })).toBeTruthy();
    },
  );
});
