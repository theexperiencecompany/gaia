import { toast } from "@/lib/toast";

const COPY_FAILED_MESSAGE =
  "Couldn't copy to the clipboard. Select the text and copy it manually.";

/** How a copy request ended: on the clipboard, or selected for the user to copy. */
export type CopyOutcome = "copied" | "selected";

async function writeWithClipboardApi(text: string): Promise<boolean> {
  // The Clipboard API exists only in a secure context, not on a self-hosted server's plain-http IP.
  if (!navigator.clipboard) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Permission denied: the legacy copy command is still worth a try.
    return false;
  }
}

/** Copy through a temporary selection; a range needs no focus, so a modal's focus trap cannot undo it. */
function copyWithSelection(text: string): boolean {
  const selection = document.getSelection();
  if (!selection) return false;
  const previousRanges = Array.from({ length: selection.rangeCount }, (_, i) =>
    selection.getRangeAt(i),
  );
  const holder = document.createElement("span");
  holder.textContent = text;
  Object.assign(holder.style, {
    position: "fixed",
    top: "0",
    opacity: "0",
    whiteSpace: "pre",
    userSelect: "text",
  });
  document.body.append(holder);
  const range = document.createRange();
  range.selectNodeContents(holder);
  selection.removeAllRanges();
  selection.addRange(range);
  try {
    return document.execCommand("copy");
  } finally {
    selection.removeAllRanges();
    for (const previous of previousRanges) selection.addRange(previous);
    holder.remove();
  }
}

/** Copy text to the clipboard, falling back to the legacy copy command; rejects when both refuse. */
export async function copyText(text: string): Promise<void> {
  if (await writeWithClipboardApi(text)) return;
  if (!copyWithSelection(text)) {
    throw new Error("The browser refused to copy to the clipboard");
  }
}

/** Copy text, telling the user when the browser refused; true when it landed on the clipboard. */
export async function copyWithFeedback(text: string): Promise<boolean> {
  try {
    await copyText(text);
    return true;
  } catch (error) {
    console.error("Copy to clipboard failed:", error);
    toast.error(COPY_FAILED_MESSAGE);
    return false;
  }
}

/**
 * Copy a text field's value. When neither copy path works the field is left
 * selected, and "selected" leaves the copy to the user.
 */
export async function copyFieldText(
  field: HTMLInputElement,
): Promise<CopyOutcome> {
  if (await writeWithClipboardApi(field.value)) return "copied";
  field.focus();
  field.select();
  return document.execCommand("copy") ? "copied" : "selected";
}
