// @vitest-environment jsdom
import { ListBox } from "@heroui/react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GaiaListBoxItem } from "./GaiaListBoxItem";

describe("GaiaListBoxItem", () => {
  it("truncates a text label to one line, as v2's item title did", () => {
    render(
      <ListBox aria-label="Timezones">
        <GaiaListBoxItem id="kolkata" textValue="Kolkata">
          Kolkata (UTC+05:30) - 00:56
        </GaiaListBoxItem>
      </ListBox>,
    );
    const label = screen.getByText("Kolkata (UTC+05:30) - 00:56");
    expect(label.tagName).toBe("SPAN");
    expect(label.classList.contains("truncate")).toBe(true);
  });

  it("renders composed content (icon and text) as given", () => {
    render(
      <ListBox aria-label="Genders">
        <GaiaListBoxItem id="female" textValue="Female">
          <svg data-testid="icon" />
          Female
        </GaiaListBoxItem>
      </ListBox>,
    );
    const option = screen.getByRole("option");
    expect(option.contains(screen.getByTestId("icon"))).toBe(true);
    expect(option.textContent).toContain("Female");
  });
});
