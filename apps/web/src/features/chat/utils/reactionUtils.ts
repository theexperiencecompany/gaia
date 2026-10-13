import { foldReactionAcks as foldSharedReactionAcks } from "@shared/utils";
import type { IMessage } from "@/lib/db/chatDb";

/**
 * Fold comms REACT acks onto their target messages for render.
 *
 * Thin wrapper over the shared implementation (`@shared/utils`) so web and
 * mobile converge on one fold. See `foldReactionAcks` there for the contract.
 */
export function foldReactionAcks(messages: IMessage[]): IMessage[] {
  return foldSharedReactionAcks(messages, (message) => message.content);
}
