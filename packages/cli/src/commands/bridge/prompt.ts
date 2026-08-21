// Minimal interactive prompt helpers over node:readline — no extra deps.

import { createInterface } from "node:readline/promises";
import { Writable } from "node:stream";

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

/** Ask without echoing the typed value (for tokens/secrets). */
export async function askSecret(question: string): Promise<string> {
  process.stdout.write(`${question}: `);
  const muted = new Writable({
    write(_chunk, _encoding, callback) {
      callback();
    },
  });
  const rl = createInterface({
    input: process.stdin,
    output: muted,
    terminal: true,
  });
  try {
    const answer = (await rl.question("")).trim();
    process.stdout.write("\n");
    return answer;
  } finally {
    rl.close();
  }
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
