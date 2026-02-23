#!/usr/bin/env node

/**
 * CI guard for CLI publish workflow.
 *
 * Validates that:
 * - tag format is `cli-v<version>`,
 * - tag/version/package.json/manifest versions are consistent,
 * - npm publish is idempotent (skip when version already exists).
 *
 * Why this exists:
 * - prevents publishing the wrong version from a mismatched tag,
 * - prevents manifest drift from silently shipping incorrect metadata,
 * - prevents failing reruns when the same version is already on npm.
 */

import { execFileSync } from "node:child_process";
import { appendFileSync, existsSync, readFileSync } from "node:fs";

const CLI_PACKAGE_PATH = "packages/cli/package.json";
const MANIFEST_PATH = "config/.release-please-manifest.json";
const MANIFEST_KEY = "packages/cli";
const NPM_PACKAGE_NAME = "@heygaia/cli";

function parseArgs(argv) {
  const args = {};

  for (let i = 0; i < argv.length; i += 1) {
    const current = argv[i];
    if (current === "--tag" || current === "--version") {
      const value = argv[i + 1];
      if (!value || value.startsWith("--")) {
        throw new Error(`Missing value for ${current}`);
      }
      args[current.slice(2)] = value;
      i += 1;
      continue;
    }

    if (current.startsWith("--tag=")) {
      args.tag = current.slice("--tag=".length);
      continue;
    }

    if (current.startsWith("--version=")) {
      args.version = current.slice("--version=".length);
      continue;
    }

    throw new Error(`Unknown argument: ${current}`);
  }

  return args;
}

function readJson(filePath) {
  if (!existsSync(filePath)) {
    throw new Error(`Missing file: ${filePath}`);
  }

  return JSON.parse(readFileSync(filePath, "utf8"));
}

function writeOutput(key, value) {
  const outputFile = process.env.GITHUB_OUTPUT;
  if (!outputFile) return;
  appendFileSync(outputFile, `${key}=${String(value)}\n`);
}

function loadPublishedVersions() {
  let raw;
  try {
    raw = execFileSync(
      "npm",
      ["view", NPM_PACKAGE_NAME, "versions", "--json"],
      {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
  } catch (error) {
    const stderr =
      typeof error.stderr === "string" ? error.stderr.trim() : String(error);
    throw new Error(`Failed to query npm versions for ${NPM_PACKAGE_NAME}: ${stderr}`);
  }

  const parsed = JSON.parse(raw.trim() || "[]");
  if (Array.isArray(parsed)) return parsed;
  if (typeof parsed === "string") return [parsed];
  throw new Error("Unexpected npm view response format");
}

function main() {
  const { tag, version } = parseArgs(process.argv.slice(2));
  const errors = [];
  const warnings = [];

  if (!tag) {
    errors.push("Missing --tag");
  }
  if (!version) {
    errors.push("Missing --version");
  }

  if (errors.length > 0) {
    for (const error of errors) {
      console.error(`[error] ${error}`);
    }
    process.exit(1);
  }

  const tagMatch = /^cli-v(.+)$/.exec(tag);
  if (!tagMatch) {
    errors.push(`Tag "${tag}" must match format cli-v<version>`);
  }

  const tagVersion = tagMatch?.[1] ?? "";
  if (tagVersion && tagVersion !== version) {
    errors.push(`Input version "${version}" does not match tag-derived version "${tagVersion}"`);
  }

  const cliPackageVersion = readJson(CLI_PACKAGE_PATH).version;
  if (cliPackageVersion !== version) {
    errors.push(
      `${CLI_PACKAGE_PATH} version "${cliPackageVersion}" does not match requested version "${version}"`,
    );
  }

  const manifest = readJson(MANIFEST_PATH);
  const manifestVersion = manifest[MANIFEST_KEY];
  if (!manifestVersion) {
    errors.push(`Missing "${MANIFEST_KEY}" entry in ${MANIFEST_PATH}`);
  }

  const publishedVersions = loadPublishedVersions();
  const versionExistsOnNpm = publishedVersions.includes(version);

  if (manifestVersion && manifestVersion !== version) {
    const mismatchMessage = `${MANIFEST_PATH} entry "${MANIFEST_KEY}" is "${manifestVersion}" but expected "${version}"`;
    if (versionExistsOnNpm) {
      warnings.push(
        `${mismatchMessage}. Non-blocking for idempotent reruns because ${NPM_PACKAGE_NAME}@${version} is already published.`,
      );
    } else {
      errors.push(mismatchMessage);
    }
  }

  const shouldPublish = !versionExistsOnNpm;

  writeOutput("tag", tag);
  writeOutput("version", version);
  writeOutput("version_exists_on_npm", versionExistsOnNpm);
  writeOutput("should_publish", shouldPublish);

  console.log(`[info] tag=${tag}`);
  console.log(`[info] version=${version}`);
  console.log(`[info] package_version=${cliPackageVersion}`);
  if (manifestVersion) {
    console.log(`[info] manifest_version=${manifestVersion}`);
  }
  console.log(`[info] npm_version_exists=${versionExistsOnNpm}`);
  console.log(`[info] should_publish=${shouldPublish}`);

  if (warnings.length > 0) {
    for (const warning of warnings) {
      console.warn(`[warn] ${warning}`);
    }
  }

  if (errors.length > 0) {
    for (const error of errors) {
      console.error(`[error] ${error}`);
    }
    process.exit(1);
  }

  if (shouldPublish) {
    console.log("[ok] Release verification passed. Version is not yet published on npm.");
  } else {
    console.log("[ok] Release verification passed. Version already exists on npm; publish can be skipped.");
  }
}

try {
  main();
} catch (error) {
  console.error(`[error] ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
}
