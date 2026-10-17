// Minimal interactive prompt helpers over node:readline — no extra deps.

import { createInterface } from "node:readline/promises";
import { Writable } from "node:stream";
import { MARK } from "../ui/constants.js";
import { SIGINT_EXIT_CODE } from "./exit-codes.js";

export async function ask(
  question: string,
  defaultValue?: string,
): Promise<string> {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  try {
    const suffix = defaultValue ? ` [${defaultValue}]` : "";
    const answer = (await rl.question(`${question}${suffix}: `)).trim();
    return answer || defaultValue || "";
  } finally {
    rl.close();
  }
}

/** Characters of a secret left readable once it is entered, so a paste can be checked. */
const SECRET_VISIBLE_TAIL = 4;
const ESC = "\u001b";
const CTRL_C = "\u0003";
const BACKSPACES = new Set(["\u007f", "\b"]);
/** A terminal escape sequence: bracketed-paste markers, arrow keys. */
const ESCAPE_SEQUENCE_RE = new RegExp(`${ESC}\\[[0-9;]*[A-Za-z~]`, "g");

/** "••••••••ABCd": a secret masked except its last few characters. */
export function maskSecret(secret: string): string {
  const visible =
    secret.length > SECRET_VISIBLE_TAIL * 2 ? SECRET_VISIBLE_TAIL : 0;
  return (
    "•".repeat(secret.length - visible) + secret.slice(secret.length - visible)
  );
}

/**
 * Ask for a token or secret: each typed or pasted character shows as •, so
 * a paste visibly landed, and the last few show once it is entered. Esc or
 * Ctrl-C cancels the command; an empty entry returns "" for the caller to judge.
 */
export async function askSecret(question: string): Promise<string> {
  process.stdout.write(`${question}\n› `);
  if (!process.stdin.isTTY) {
    const rl = createInterface({
      input: process.stdin,
      output: new Writable({ write: (_c, _e, cb) => cb() }),
    });
    try {
      return (await rl.question("")).trim();
    } finally {
      rl.close();
    }
  }
  return new Promise((resolve) => {
    let value = "";
    const finish = (answer: string, shown: string): void => {
      process.stdin.off("data", onData);
      process.stdin.setRawMode(false);
      process.stdin.pause();
      process.stdout.write(`\r› ${shown}${ESC}[K\n`);
      resolve(answer);
    };
    const onData = (chunk: Buffer): void => {
      // Terminal escape sequences (bracketed-paste markers, arrow keys) are not
      // part of the secret.
      const text = chunk.toString("utf-8").replace(ESCAPE_SEQUENCE_RE, "");
      if (text === CTRL_C || text === ESC) {
        finish("", "");
        process.stdout.write(
          `${MARK.cancelled} Cancelled · nothing changed.\n`,
        );
        process.exit(SIGINT_EXIT_CODE);
      }
      for (const ch of text) {
        if (ch === "\r" || ch === "\n") {
          finish(value.trim(), maskSecret(value.trim()));
          return;
        }
        if (BACKSPACES.has(ch)) value = value.slice(0, -1);
        else if (ch >= " ") value += ch;
      }
      process.stdout.write(`\r› ${"•".repeat(value.length)}${ESC}[K`);
    };
    process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdin.on("data", onData);
  });
}

export async function confirm(
  question: string,
  defaultYes = true,
): Promise<boolean> {
  const answer = await ask(`${question} (${defaultYes ? "Y/n" : "y/N"})`);
  if (!answer) return defaultYes;
  return /^y(es)?$/i.test(answer);
}

/** Numbered menu; returns the chosen index. */
export async function choose(
  question: string,
  options: string[],
): Promise<number> {
  process.stdout.write(`\n${question}\n`);
  options.forEach((option, i) => {
    process.stdout.write(`  ${i + 1}. ${option}\n`);
  });
  for (;;) {
    const answer = await ask(`Choose 1-${options.length}`);
    const index = Number.parseInt(answer, 10) - 1;
    if (index >= 0 && index < options.length) return index;
    process.stdout.write("Invalid choice, try again.\n");
  }
}
