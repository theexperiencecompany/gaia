import cronstrue from "cronstrue";

/**
 * A plain-English description of a cron expression ("At 08:00 AM, Monday
 * through Friday"), or undefined when cronstrue cannot read it. Description
 * only: whether a schedule is acceptable is the server's call.
 */
export function describeCron(cron: string): string | undefined {
  const expression = cron.trim();
  if (!expression) return undefined;
  try {
    return cronstrue.toString(expression, {
      throwExceptionOnParseError: true,
      verbose: false,
    });
  } catch {
    return undefined;
  }
}
