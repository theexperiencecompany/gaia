/**
 * One user's inbound messages, handled one at a time and in order, for the
 * adapters whose platform does not already order them (Telegram, WhatsApp,
 * iMessage). A control command that acts on work already running jumps the
 * queue: queued behind that work, it would only run once the work was done.
 *
 * @module
 */
import { stopCommand } from "../commands/stop";

/** Commands handled the moment they arrive, ahead of the sender's queued messages. */
const OUT_OF_ORDER_COMMANDS: ReadonlySet<string> = new Set([stopCommand.name]);

/** The command a message invokes, lowercased and without a `@botname` suffix; null for plain text. */
function invokedCommand(text: string): string | null {
  const match = /^\/([^\s@]+)/.exec(text.trimStart());
  return match ? match[1].toLowerCase() : null;
}

/** Whether a message is a command that must not wait behind the sender's earlier messages. */
function runsOutOfOrder(text: string | undefined): boolean {
  const command = text === undefined ? null : invokedCommand(text);
  return command !== null && OUT_OF_ORDER_COMMANDS.has(command);
}

/** Per-sender FIFO of message handlers; {@link OUT_OF_ORDER_COMMANDS} skip it. */
export class PerUserInboundQueue {
  private readonly tails = new Map<string, Promise<void>>();

  /**
   * Runs handle after every earlier message from sender has been handled, or at
   * once when text is an out-of-order command. Settles with handle's outcome; a
   * failure never holds up the sender's next message.
   */
  enqueue(
    sender: string,
    text: string | undefined,
    handle: () => Promise<void>,
  ): Promise<void> {
    if (runsOutOfOrder(text)) return handle();
    const task = (this.tails.get(sender) ?? Promise.resolve()).then(handle);
    const tail = task.catch(() => undefined);
    this.tails.set(sender, tail);
    void tail.then(() => {
      if (this.tails.get(sender) === tail) this.tails.delete(sender);
    });
    return task;
  }

  /** Settles once every message queued so far has been handled. */
  async settled(): Promise<void> {
    await Promise.all(this.tails.values());
  }
}
