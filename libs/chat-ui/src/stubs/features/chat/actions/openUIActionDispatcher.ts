/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type { ActionEvent } from "@openuidev/react-lang";

export async function dispatchOpenUIAction(
  _event: ActionEvent,
  _appendToInput: (text: string) => void,
): Promise<void> {}
