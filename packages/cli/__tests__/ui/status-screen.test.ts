import { stripVTControlCharacters } from "node:util";
import { createElement } from "react";
import { describe, expect, it } from "vitest";
import type { StatusRow } from "../../src/commands/status/report.types.js";
import { ReportRow } from "../../src/ui/screens/status.js";
import { renderOn } from "./fake-terminal.js";

/** The label column every row's values start after. */
const VALUE_COLUMN = 8;

/** The row's lines, as a 60-column terminal shows them. */
function drawnAt60(row: StatusRow): string[] {
  const { written, app } = renderOn(createElement(ReportRow, { row }), 60, 24, {
    debug: true,
  });
  app.unmount();
  const lines = stripVTControlCharacters(written())
    .split("\n")
    .filter((line) => line.trim());
  return lines.slice(lines.lastIndexOf(lines[0] ?? ""));
}

describe("status rows on a 60-column terminal", () => {
  it("wraps a long list of services inside the value column", () => {
    const lines = drawnAt60({
      label: "Data",
      tone: "ok",
      items: ["MongoDB", "PostgreSQL", "Redis", "RabbitMQ", "ChromaDB"].map(
        (name) => ({ ok: true, name }),
      ),
    });

    expect(lines.length).toBeGreaterThan(1);
    for (const line of lines.slice(1)) {
      expect(line.slice(0, VALUE_COLUMN).trim()).toBe("");
    }
  });

  it("wraps a long note inside the value column", () => {
    const lines = drawnAt60({
      label: "Setup",
      tone: "warn",
      items: [],
      note: "not finished · open http://192.168.139.128:3000/setup",
    });

    expect(lines[0]?.startsWith("Setup")).toBe(true);
    expect(lines[0]).toContain("not finished");
    for (const line of lines.slice(1)) {
      expect(line.slice(0, VALUE_COLUMN).trim()).toBe("");
    }
  });
});
