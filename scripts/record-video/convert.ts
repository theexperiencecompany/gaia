// scripts/record-video/convert.ts
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export type Quality = "low" | "medium" | "high";

export const QUALITY_PRESET: Record<Quality, { crf: number; preset: string }> = {
  low: { crf: 32, preset: "faster" },
  medium: { crf: 23, preset: "medium" },
  high: { crf: 18, preset: "slow" },
};

export async function checkFfmpegInstalled(): Promise<void> {
  try {
    await execFileAsync("ffmpeg", ["-version"]);
  } catch {
    throw new Error(
      "ffmpeg not found. Install it with:\n  brew install ffmpeg (macOS)\n  apt install ffmpeg (Ubuntu)",
    );
  }
}

export async function convertWebmToMp4(
  inputPath: string,
  outputPath: string,
  quality: Quality = "high",
): Promise<void> {
  if (!existsSync(inputPath)) {
    throw new Error(`Input file not found: ${inputPath}`);
  }

  const { crf, preset } = QUALITY_PRESET[quality];

  const args = [
    "-y",
    "-i", inputPath,
    "-c:v", "libx264",
    "-crf", String(crf),
    "-preset", preset,
    "-r", "30",
    "-pix_fmt", "yuv420p",
    "-movflags", "+faststart",
    outputPath,
  ];

  console.log(`Converting ${inputPath} → ${outputPath} (quality: ${quality})`);

  try {
    await execFileAsync("ffmpeg", args);
    console.log(`✓ Video saved: ${outputPath}`);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(`FFmpeg conversion failed: ${msg}`);
  }
}
