#!/usr/bin/env node

/**
 * release.mjs — the release-metadata guards, in Node.
 *
 * Subcommands:
 *   validate-manifest             Check the release-please config + manifest
 *                                 against the actual package versions
 *                                 (`package.json` / `pyproject.toml`) for every
 *                                 configured release path.
 *   verify-cli --tag T --version V
 *                                 Guard the CLI publish workflow: tag format,
 *                                 tag/version/package.json/manifest agreement,
 *                                 and whether the version is already on npm.
 *                                 Writes tag / version / version_exists_on_npm
 *                                 / should_publish to $GITHUB_OUTPUT.
 *
 * Why this exists:
 * - catches manifest drift after manual version bumps or partial releases,
 * - prevents release-please from generating incorrect tags/changelogs,
 * - prevents publishing the wrong version from a mismatched tag,
 * - prevents failing reruns when the same version is already on npm,
 * - fails fast in quality checks instead of during release automation.
 *
 * The shell half of the same concept (image tags, :latest, dispatching the
 * publish) lives in release.sh.
 */

import { execFileSync } from "node:child_process";
import { appendFileSync, existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const MANIFEST_PATH = "config/.release-please-manifest.json";
const RELEASE_CONFIG_PATH = "config/release-please-config.json";
const CLI_PACKAGE_PATH = "packages/cli/package.json";
const CLI_MANIFEST_KEY = "packages/cli";
const NPM_PACKAGE_NAME = "@heygaia/cli";

function readJson(filePath) {
  if (!existsSync(filePath)) {
    throw new Error(`Missing file: ${filePath}`);
  }
  return JSON.parse(readFileSync(filePath, "utf8"));
}

function readVersionFromPackageJson(filePath) {
  const data = readJson(filePath);
  if (!data.version || typeof data.version !== "string") {
    throw new Error(`Missing string "version" in ${filePath}`);
  }
  return data.version;
}

function readVersionFromPyProject(filePath) {
  const content = readFileSync(filePath, "utf8");
  const match = /^\s*version\s*=\s*"([^"]+)"\s*$/m.exec(content);
  if (!match) {
    throw new Error(`Could not find version = \"...\" in ${filePath}`);
  }
  return match[1];
}

function resolveVersionFile(packagePath) {
  const packageJsonPath = join(packagePath, "package.json");
  if (existsSync(packageJsonPath)) {
    return {
      filePath: packageJsonPath,
      readVersion: () => readVersionFromPackageJson(packageJsonPath),
    };
  }

  const pyprojectPath = join(packagePath, "pyproject.toml");
  if (existsSync(pyprojectPath)) {
    return {
      filePath: pyprojectPath,
      readVersion: () => readVersionFromPyProject(pyprojectPath),
    };
  }

  return null;
}

function cmdValidateManifest() {
  const manifest = readJson(MANIFEST_PATH);
  const releaseConfig = readJson(RELEASE_CONFIG_PATH);

  const manifestPaths = Object.keys(manifest).sort();
  const configPaths = Object.keys(releaseConfig.packages ?? {}).sort();

  const errors = [];

  for (const configPath of configPaths) {
    if (!(configPath in manifest)) {
      errors.push(`Missing manifest entry for configured package "${configPath}"`);
    }
  }

  for (const manifestPath of manifestPaths) {
    if (!configPaths.includes(manifestPath)) {
      errors.push(`Manifest entry "${manifestPath}" is not present in ${RELEASE_CONFIG_PATH}`);
    }

    const resolver = resolveVersionFile(manifestPath);
    if (!resolver) {
      errors.push(`No package.json or pyproject.toml found for "${manifestPath}"`);
      continue;
    }

    let actualVersion;
    try {
      actualVersion = resolver.readVersion();
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));
      continue;
    }

    const manifestVersion = manifest[manifestPath];
    if (manifestVersion !== actualVersion) {
      errors.push(
        `Version mismatch for "${manifestPath}": manifest=${manifestVersion} file=${actualVersion} (${resolver.filePath})`,
      );
      continue;
    }

    console.log(
      `[ok] ${manifestPath} -> ${manifestVersion} (${resolver.filePath})`,
    );
  }

  if (errors.length > 0) {
    for (const error of errors) {
      console.error(`[error] ${error}`);
    }
    process.exit(1);
  }

  console.log("[ok] Release manifest is consistent with all configured package versions.");
}

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

function cmdVerifyCli(argv) {
  const { tag, version } = parseArgs(argv);
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
  const manifestVersion = manifest[CLI_MANIFEST_KEY];
  if (!manifestVersion) {
    errors.push(`Missing "${CLI_MANIFEST_KEY}" entry in ${MANIFEST_PATH}`);
  }

  const publishedVersions = loadPublishedVersions();
  const versionExistsOnNpm = publishedVersions.includes(version);

  if (manifestVersion && manifestVersion !== version) {
    const mismatchMessage = `${MANIFEST_PATH} entry "${CLI_MANIFEST_KEY}" is "${manifestVersion}" but expected "${version}"`;
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

function usage() {
  console.error(
    [
      "usage: node scripts/ci/release.mjs <subcommand> [args]",
      "",
      "  validate-manifest                 release-please manifest vs package versions",
      "  verify-cli --tag T --version V    CLI publish guard (tag/version/npm)",
    ].join("\n"),
  );
}

function main() {
  const sub = process.argv[2];
  const rest = process.argv.slice(3);
  switch (sub) {
    case "validate-manifest":
      cmdValidateManifest();
      break;
    case "verify-cli":
      cmdVerifyCli(rest);
      break;
    default:
      console.error(`release.mjs: unknown subcommand '${sub ?? ""}'`);
      usage();
      process.exit(2);
  }
}

try {
  main();
} catch (error) {
  console.error(`[error] ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
}
