/**
 * Parse and format Google Calendar recurrence rules (RRULE format)
 * Example inputs:
 * - "RRULE:FREQ=DAILY"
 * - "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
 * - "RRULE:FREQ=MONTHLY;BYMONTHDAY=15"
 */
export function formatRecurrence(recurrence?: string[]): string | null {
  if (!recurrence || recurrence.length === 0) return null;

  const rrule = recurrence[0];
  if (!rrule.startsWith("RRULE:")) return null;

  const rules = rrule.replace("RRULE:", "").split(";");
  const ruleMap: Record<string, string> = {};

  rules.forEach((rule) => {
    const [key, value] = rule.split("=");
    if (key && value) {
      ruleMap[key] = value;
    }
  });

  const freq = ruleMap["FREQ"];
  if (!freq) return null;

  // Handle weekday recurrence (Mon-Fri)
  if (freq === "WEEKLY" && ruleMap["BYDAY"] === "MO,TU,WE,TH,FR") {
    return "Every weekday";
  }

  // Handle specific days of the week
  if (freq === "WEEKLY" && ruleMap["BYDAY"]) {
    const dayMap: Record<string, string> = {
      MO: "Monday",
      TU: "Tuesday",
      WE: "Wednesday",
      TH: "Thursday",
      FR: "Friday",
      SA: "Saturday",
      SU: "Sunday",
    };

    const days = ruleMap["BYDAY"]
      .split(",")
      .map((day) => dayMap[day] || day)
      .join(", ");

    return `Every ${days}`;
  }

  // Handle monthly recurrence with specific day
  if (freq === "MONTHLY" && ruleMap["BYMONTHDAY"]) {
    const day = ruleMap["BYMONTHDAY"];
    return `Monthly on day ${day}`;
  }

  // Handle yearly recurrence
  if (freq === "YEARLY") {
    return "Annually";
  }

  // Handle basic frequencies
  switch (freq) {
    case "DAILY":
      return "Daily";
    case "WEEKLY":
      return "Weekly";
    case "MONTHLY":
      return "Monthly";
    case "YEARLY":
      return "Yearly";
    default:
      return `Repeats ${freq.toLowerCase()}`;
  }
}
