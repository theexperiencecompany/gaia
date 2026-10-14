/** How a copy request ended: on the clipboard, or selected for the user to copy. */
export type CopyOutcome = "copied" | "selected";

/**
 * Copy a text field's value. The Clipboard API exists only in a secure
 * context, so on a plain-http origin (a self-hosted server's IP) the field is
 * selected and the legacy copy command tried; "selected" leaves it to the user.
 */
export async function copyFieldText(
  field: HTMLInputElement,
): Promise<CopyOutcome> {
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(field.value);
      return "copied";
    } catch {
      // Permission denied: the selection below still lets the user copy it.
    }
  }
  field.focus();
  field.select();
  return document.execCommand("copy") ? "copied" : "selected";
}
