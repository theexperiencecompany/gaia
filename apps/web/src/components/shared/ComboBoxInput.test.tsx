// @vitest-environment jsdom
import { ComboBox, ListBox } from "@heroui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { ComboBoxInput } from "./ComboBoxInput";

function Country({
  onSelectionChange = vi.fn(),
  onClear = vi.fn(),
  defaultSelectedKey,
}: {
  onSelectionChange?: (key: unknown) => void;
  onClear?: () => void;
  defaultSelectedKey?: string;
}) {
  return (
    <ComboBox
      aria-label="Country"
      defaultSelectedKey={defaultSelectedKey}
      onSelectionChange={onSelectionChange}
    >
      <ComboBoxInput
        placeholder="Country"
        startContent={<span data-testid="flag" />}
        endContent={<span>+5:30</span>}
        isClearable
        onClear={onClear}
      />
      <ComboBox.Popover>
        <ListBox>
          <GaiaListBoxItem id="in" textValue="India">
            India
          </GaiaListBoxItem>
        </ListBox>
      </ComboBox.Popover>
    </ComboBox>
  );
}

describe("ComboBoxInput", () => {
  it("shows the start and end content around the typed text", () => {
    render(<Country defaultSelectedKey="in" />);
    expect(screen.getByTestId("flag")).toBeTruthy();
    expect(screen.getByText("+5:30")).toBeTruthy();
  });

  it("clears the selection and the text, and says so", () => {
    const onSelectionChange = vi.fn();
    const onClear = vi.fn();
    render(
      <Country
        defaultSelectedKey="in"
        onSelectionChange={onSelectionChange}
        onClear={onClear}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe("");
    expect(onSelectionChange).toHaveBeenLastCalledWith(null);
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("offers no clear button while empty, and the trigger still opens the list", () => {
    render(<Country />);
    expect(screen.queryByRole("button", { name: "Clear" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Show suggestions" }),
    ).toBeTruthy();
  });
});
