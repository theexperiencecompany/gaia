#!/usr/bin/env node

/**
 * CI guard for release metadata consistency.
 *
 * Checks release-please config + manifest against actual package versions
 * (`package.json` / `pyproject.toml`) for every configured release path.
 *
 * Why this exists:
 * - catches manifest drift after manual version bumps or partial releases,
 * - prevents release-please from generating incorrect tags/changelogs,
 * - fails fast in quality checks instead of during release automation.
 */

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const MANIFEST_PATH = "config/.release-please-manifest.json";
const RELEASE_CONFIG_PATH = "config/release-please-config.json";

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

function main() {
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

try {
  main();
} catch (error) {
  console.error(`[error] ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
}
