import { checkFfmpegInstalled } from "./convert.js";
import { recordScenario, type Format } from "./record.js";

function parseArgs(args: string[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith("--")) {
      const key = args[i].slice(2);
      const value =
        args[i + 1] && !args[i + 1].startsWith("--") ? args[++i] : "true";
      result[key] = value;
    }
  }
  return result;
}

function printUsage() {
  console.log(`
Usage: pnpm record --scenario <id> [options]

Options:
  --scenario <id>        Scenario JSON filename (without .json)  [required]
  --format <9:16|16:9>   Aspect ratio                            [default: 9:16]
  --output <path>        Output file path                        [default: output/videos/<id>-<format>.mp4]
  --dev-server-url <url> URL of running dev server               [default: http://localhost:3000]
  --quality <low|medium|high>  FFmpeg encoding preset            [default: high]
  --timeout <ms>         Max wait time for scenario completion   [default: 300000]
  --list                 List available scenarios

Examples:
  pnpm record --scenario calendar-booking-demo
  pnpm record --scenario todo-management-demo --format 16:9
  pnpm record --scenario web-search-demo --quality medium --output my-video.mp4
`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.list !== undefined) {
    const { readdirSync } = await import("node:fs");
    const { join } = await import("node:path");
    const scenariosDir = join(
      process.cwd(),
      "../../apps/web/public/scenarios"
    );
    try {
      const files = readdirSync(scenariosDir).filter((f) =>
        f.endsWith(".json")
      );
      console.log("\nAvailable scenarios:");
      files.forEach((f) => console.log(`  ${f.replace(".json", "")}`));
      console.log();
    } catch {
      console.log(
        "No scenarios directory found at apps/web/public/scenarios/"
      );
    }
    process.exit(0);
  }

  if (!args.scenario) {
    printUsage();
    process.exit(1);
  }

  const format = (args.format ?? "9:16") as Format;
  if (format !== "9:16" && format !== "16:9") {
    console.error(`Invalid format: ${format}. Must be "9:16" or "16:9"`);
    process.exit(1);
  }

  const quality = (args.quality ?? "high") as "low" | "medium" | "high";
  if (!["low", "medium", "high"].includes(quality)) {
    console.error(`Invalid quality: ${quality}. Must be low, medium, or high`);
    process.exit(1);
  }

  console.log("Checking FFmpeg...");
  await checkFfmpegInstalled();
  console.log("✓ FFmpeg found");

  try {
    const outputPath = await recordScenario({
      scenarioId: args.scenario,
      format,
      outputPath: args.output,
      devServerUrl: args["dev-server-url"],
      quality,
      timeoutMs: args.timeout ? Number(args.timeout) : undefined,
    });

    console.log(`\n🎬 Done! Video saved to: ${outputPath}\n`);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`\n✗ Recording failed: ${msg}\n`);
    process.exit(1);
  }
}

main();
