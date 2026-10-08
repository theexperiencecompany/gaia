import { describe, expect, it } from "vitest";

import { describeCron } from "./cronUtils";

const TOO_FREQUENT = "Schedules can repeat at most once an hour.";
const FIVE_FIELDS = "Use 5 fields: minute hour day month weekday.";

describe("describeCron applies the server's recurring-schedule rule", () => {
  it.each([
    "* * * * *",
    "*/5 * * * *",
    "*/30 * * * *",
    "0,30 * * * *",
    "0-59 * * * *",
  ])("refuses %s as too frequent", (cron) => {
    expect(describeCron(cron)).toEqual({ isValid: false, error: TOO_FREQUENT });
  });

  it.each(["0 6 30 * * *", "* * * * * *", "0 9 * * * 0 2026", "0 9 * *"])(
    "refuses %s for its field count",
    (cron) => {
      expect(describeCron(cron)).toEqual({
        isValid: false,
        error: FIVE_FIELDS,
      });
    },
  );

  it.each(["0 * * * *", "0 9 * * 1-5", "0 9,20 * * *", "0 */2 * * *"])(
    "accepts %s and describes it",
    (cron) => {
      const result = describeCron(cron);
      expect(result.isValid).toBe(true);
      expect(result.description).toBeTruthy();
    },
  );

  it("still reports an unreadable expression", () => {
    const result = describeCron("a b c d e");
    expect(result.isValid).toBe(false);
    expect(result.error).toBeTruthy();
  });
});
