import fs from "fs";
import { globSync } from "glob";
import path from "path";

const publicDir = path.join(process.cwd(), "public");

// Get all images in public/
const imageFiles = globSync(`${publicDir}/**/*.{png,jpg,jpeg,gif,svg,webp}`);

// Get all source files including manifest and config files
const sourceFiles = globSync(
  "{src,pages,app,components}/**/*.{js,jsx,ts,tsx,html,css,mdx}",
);

// Also check manifest and config files in public/
const configFiles = globSync("public/*.{json,webmanifest}");

const usedImages = new Set();

// Check source files
for (const file of sourceFiles) {
  const content = fs.readFileSync(file, "utf-8");
  for (const image of imageFiles) {
    const relativePath = image.replace(publicDir, "");
    if (content.includes(relativePath)) {
      usedImages.add(image);
    }
  }
}

// Check manifest and config files
for (const file of configFiles) {
  const content = fs.readFileSync(file, "utf-8");
  for (const image of imageFiles) {
    const relativePath = image.replace(publicDir, "");
    // For manifest files, also check without leading slash
    const relativePathNoSlash = relativePath.startsWith("/")
      ? relativePath.slice(1)
      : relativePath;
    if (
      content.includes(relativePath) ||
      content.includes(relativePathNoSlash)
    ) {
      usedImages.add(image);
    }
  }
}

const unused = imageFiles.filter((img) => !usedImages.has(img));

console.log("Unused images:");
console.log(unused.length ? unused : "None 🎉");
