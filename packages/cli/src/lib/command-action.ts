import { printError } from "./print-error.js";

/** Commander swallows async rejections, so every action reports its own failure. */
export async function runAction(
  action: () => void | Promise<void>,
): Promise<void> {
  try {
    await action();
  } catch (error) {
    printError(error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}
