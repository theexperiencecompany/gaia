/**
 * Every image under public/images is referenced by a tracked file. An image
 * nobody points at still ships in every build and every clone, so a removed
 * usage must take its asset with it. Integration logos are resolved through
 * the shared registry, which builds their paths at runtime.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import {
  getWebIntegrationLogoPath,
  INTEGRATION_LOGO_FILES,
} from "@shared/icons";
import { describe, expect, it } from "vitest";

const REPO_ROOT = path.resolve(process.cwd(), "../..");
const PUBLIC_IMAGES_DIR = "apps/web/public/images/";
const PUBLIC_DIR = "apps/web/public";

const IMAGE_FILE = /\.(png|jpe?g|gif|webp|avif|svg|ico)$/i;
const BINARY_FILE =
  /\.(png|jpe?g|gif|webp|avif|ico|icns|woff2?|ttf|otf|eot|mp3|mp4|wav|webm|mov|zip|gz|pdf|onnx|tflite|bin|ppn|jar|keystore|db|sqlite|lottie|riv)$/i;
/** A public image URL as written in source, markdown, JSON or CSS. */
const IMAGE_URL = /\/images\/[\w\-./@%]+/g;

function trackedFiles(): string[] {
  return execFileSync("git", ["ls-files", "-z"], {
    cwd: REPO_ROOT,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  })
    .split("\0")
    .filter(Boolean);
}

function referencedImageUrls(files: string[]): Set<string> {
  const urls = new Set<string>();
  for (const file of files) {
    const absolute = path.join(REPO_ROOT, file);
    if (BINARY_FILE.test(file) || !existsSync(absolute)) continue;
    for (const [url] of readFileSync(absolute, "utf8").matchAll(IMAGE_URL)) {
      urls.add(decodeURIComponent(url).replace(/\.+$/, ""));
    }
  }
  for (const key of Object.keys(INTEGRATION_LOGO_FILES)) {
    const logo = getWebIntegrationLogoPath(key);
    if (logo) urls.add(logo);
  }
  return urls;
}

describe("public/images", () => {
  it("contains only images some tracked file references", () => {
    const files = trackedFiles();
    const referenced = referencedImageUrls(files);
    const unreferenced = files
      .filter((f) => f.startsWith(PUBLIC_IMAGES_DIR) && IMAGE_FILE.test(f))
      .map((f) => f.slice(PUBLIC_DIR.length))
      .filter((url) => !referenced.has(url));
    expect(unreferenced).toEqual([]);
  });
});
