/**
 * `gaia-sim` CLI — drives the harness against a running GAIA API.
 *
 *   gaia-sim send --emulate telegram --user dev@gaia.local --out t.jsonl "hi"
 *   gaia-sim run scenarios/plain-reply.yaml --out run.jsonl
 *
 * `send` is one-shot: mint + link the dev user, inject the message as that
 * platform user, await the streamed reply, write + print the transcript.
 * `run` executes a multi-turn YAML scenario and checks its transcript
 * assertions, exiting non-zero if any fail.
 */

import { readFile } from "node:fs/promises";
import { parse as parseYaml } from "yaml";
import { isEmulatablePlatform } from "./emulation";
import {
  resolveApiUrl,
  runScenario,
  type ScenarioResult,
  type SendResult,
  sendOneShot,
} from "./runner";
import type { Scenario } from "./scenario.types";
import type { TranscriptRecorder } from "./transcript";

/** Writes a line to stdout (transcript/data output). */
function out(line: string): void {
  process.stdout.write(`${line}\n`);
}

/** Writes a line to stderr (human-facing status/errors). */
function log(line: string): void {
  process.stderr.write(`${line}\n`);
}

interface ParsedArgs {
  flags: Record<string, string>;
  positionals: string[];
}

/** Parses `--key value` / `--key=value` flags and positional arguments. */
function parseArgs(argv: string[]): ParsedArgs {
  const flags: Record<string, string> = {};
  const positionals: string[] = [];
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg.startsWith("--")) {
      const eq = arg.indexOf("=");
      if (eq !== -1) {
        flags[arg.slice(2, eq)] = arg.slice(eq + 1);
      } else {
        const next = argv[i + 1];
        if (next !== undefined && !next.startsWith("--")) {
          flags[arg.slice(2)] = next;
          i += 1;
        } else {
          flags[arg.slice(2)] = "true";
        }
      }
    } else {
      positionals.push(arg);
    }
  }
  return { flags, positionals };
}

/** Prints usage help. */
function printUsage(): void {
  log(
    [
      "Usage:",
      "  gaia-sim send --emulate <platform> --user <email> [--out <file>] [--api <url>] [--channel <id>] <message>",
      "  gaia-sim run <scenario.yaml> [--out <file>] [--api <url>]",
      "",
      "  platforms: discord | slack | telegram | whatsapp",
    ].join("\n"),
  );
}

/** Warns loudly when the outbound consumer will be disabled. */
function warnIfNoBroker(): void {
  if (!process.env.RABBITMQ_URL) {
    log(
      "WARNING: RABBITMQ_URL is not set — the outbound consumer is disabled, so " +
        "backend-originated (proactive) messages will NOT appear as outbound-delivery events.",
    );
  }
}

/** Prints a transcript (JSONL to stdout) and optionally writes it to a file. */
async function emitTranscript(
  transcript: TranscriptRecorder,
  outPath: string | undefined,
): Promise<void> {
  out(transcript.toJsonl());
  if (outPath) {
    await transcript.writeTo(outPath);
    log(`Transcript written to ${outPath}`);
  }
}

async function runSend(args: ParsedArgs): Promise<number> {
  const emulate = args.flags.emulate;
  const email = args.flags.user;
  const message = args.positionals.join(" ").trim();

  if (!emulate || !isEmulatablePlatform(emulate)) {
    log(`Error: --emulate must be one of discord|slack|telegram|whatsapp`);
    return 1;
  }
  if (!email) {
    log("Error: --user <email> is required");
    return 1;
  }
  if (!message) {
    log("Error: a message argument is required");
    return 1;
  }

  const apiUrl = resolveApiUrl(args.flags.api);
  warnIfNoBroker();
  log(`Emulating ${emulate} as ${email} against ${apiUrl}`);

  const result: SendResult = await sendOneShot({
    apiUrl,
    emulate,
    email,
    message,
    channelId: args.flags.channel,
  });

  log(`Injected as platform user ${result.user.platformUserId}`);
  await emitTranscript(result.transcript, args.flags.out);
  return 0;
}

async function runRun(args: ParsedArgs): Promise<number> {
  const scenarioPath = args.positionals[0];
  if (!scenarioPath) {
    log("Error: a scenario file path is required");
    return 1;
  }

  const raw = await readFile(scenarioPath, "utf8");
  const scenario = parseYaml(raw) as Scenario;
  // Platform validation is runScenario's job (single authoritative guard);
  // its throw is caught and reported by main().

  const apiUrl = resolveApiUrl(args.flags.api);
  warnIfNoBroker();
  log(`Running scenario "${scenario.name}" (emulate ${scenario.emulate})`);

  const result: ScenarioResult = await runScenario(scenario, apiUrl);
  await emitTranscript(result.transcript, args.flags.out);

  if (result.passed) {
    log(`PASS: ${result.name} (${scenario.turns.length} turn(s))`);
    return 0;
  }
  log(`FAIL: ${result.name}`);
  for (const failure of result.failures) {
    log(`  - ${failure}`);
  }
  return 1;
}

async function main(): Promise<number> {
  const [, , command, ...rest] = process.argv;
  const args = parseArgs(rest);

  switch (command) {
    case "send":
      return runSend(args);
    case "run":
      return runRun(args);
    default:
      printUsage();
      return command ? 1 : 0;
  }
}

// exitCode (not process.exit) lets pending stdout writes — the JSONL
// transcript can be large — flush before the process ends.
try {
  process.exitCode = await main();
} catch (error: unknown) {
  log(
    `gaia-sim failed: ${error instanceof Error ? error.message : String(error)}`,
  );
  process.exitCode = 1;
}
