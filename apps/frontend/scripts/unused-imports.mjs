import { execSync } from "child_process";
import fs from "fs";

const iconsFile = "../src/components/shared/icons.tsx";
const projectDir = "../src"; // search in src directory
const iconsFileName = "icons.tsx";

const content = fs.readFileSync(iconsFile, "utf8");

// Match export const X = Y;
const regex = /export const (\w+)\s*=/g;

let match;
const icons = [];

while ((match = regex.exec(content)) !== null) {
  icons.push(match[1]);
}

console.log(`Found ${icons.length} icons\n`);
console.log("Checking usage...\n");

const unused = [];

for (const icon of icons) {
  // Use ripgrep (rg) if available, otherwise grep
  // Search for the icon name as a word boundary to avoid partial matches
  // Exclude the icons file and common directories

  try {
    const cmd = `grep -r "\\b${icon}\\b" ${projectDir} \
      --exclude="${iconsFileName}" \
      --exclude-dir=node_modules \
      --exclude-dir=.next \
      --exclude-dir=dist \
      --exclude-dir=build \
      --exclude="*.test.*" \
      --exclude="*.spec.*" \
      2>/dev/null || true`;

    const result = execSync(cmd, {
      encoding: "utf8",
      maxBuffer: 10 * 1024 * 1024, // 10MB buffer
    });

    // Filter out the definition itself
    const lines = result
      .split("\n")
      .filter((line) => line.trim())
      .filter((line) => !line.includes(iconsFile))
      .filter((line) => !line.match(new RegExp(`export\\s+const\\s+${icon}`)));

    if (lines.length === 0) {
      unused.push(icon);
    } else {
      console.log(
        `✓ ${icon} (${lines.length} usage${lines.length > 1 ? "s" : ""})`,
      );
    }
  } catch (error) {
    console.error(`Error checking ${icon}:`, error.message);
  }
}

console.log("\n" + "=".repeat(50));
console.log(`\n❌ UNUSED ICONS (${unused.length}):\n`);
if (unused.length > 0) {
  unused.forEach((x) => console.log(`  - ${x}`));
} else {
  console.log("  All icons are being used! 🎉");
}
console.log("\n" + "=".repeat(50));
