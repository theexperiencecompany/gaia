#!/usr/bin/env node

/**
 * Generates filtered release notes sub-pages from the main release-notes.mdx.
 *
 * Source of truth: docs/release-notes.mdx
 * Output: docs/release-notes/{api,web,desktop,mobile,bots,cli,features,bug-fixes,improvements,2025,2026}.mdx
 *
 * Run: node docs/scripts/generate-changelog-pages.js
 * Or:  mise run generate  (from the docs/ directory)
 */

const fs = require("fs");
const path = require("path");

const DOCS_DIR = path.resolve(__dirname, "..");
const SOURCE = path.join(DOCS_DIR, "release-notes.mdx");
const OUT_DIR = path.join(DOCS_DIR, "release-notes");

// --- Parse ---

function parseSource() {
  const raw = fs.readFileSync(SOURCE, "utf-8");

  // Strip frontmatter and hero image
  const bodyStart = raw.indexOf("---", raw.indexOf("---") + 3) + 3;
  const body = raw.slice(bodyStart).trim();

  // Split into Update blocks
  const blocks = [];
  const updateRegex = /<Update\s+label="([^"]+)"(?:\s+description="([^"]*)")?>/g;
  let match;
  const positions = [];

  while ((match = updateRegex.exec(body)) !== null) {
    positions.push({
      start: match.index,
      label: match[1],
      description: match[2] || "",
      headerEnd: match.index + match[0].length,
    });
  }

  for (let i = 0; i < positions.length; i++) {
    const pos = positions[i];
    const endTag = "</Update>";
    const blockEnd = i + 1 < positions.length
      ? positions[i + 1].start
      : body.length;

    // Find the closing </Update> before the next block
    const closeIdx = body.lastIndexOf(endTag, blockEnd);
    const innerContent = body.slice(pos.headerEnd, closeIdx).trim();

    // Extract year from label (e.g. "Apr 5, 2026")
    const yearMatch = pos.label.match(/(20\d{2})/);
    const year = yearMatch ? yearMatch[1] : null;

    blocks.push({
      label: pos.label,
      description: pos.description,
      year: year,
      content: innerContent,
      raw: body.slice(pos.start, closeIdx + endTag.length),
    });
  }

  return blocks;
}

// --- Extract app sections from a block ---

function extractAppSections(content) {
  // Split by ## [App vX.Y.Z] headings and the --- separators
  const APP_HEADING = /^## \[(\w+)\s+v[\d.]+\]/im;
  const lines = content.split("\n");

  const sections = [];
  let currentApp = null;
  let currentLines = [];
  let headerLines = []; // Lines before first ## (the h1 title etc.)

  for (const line of lines) {
    const appMatch = line.match(APP_HEADING);
    if (appMatch) {
      if (currentApp) {
        sections.push({ app: currentApp.toLowerCase(), lines: trimSeparators(currentLines) });
      }
      currentApp = appMatch[1];
      currentLines = [line];
    } else if (currentApp) {
      currentLines.push(line);
    } else {
      headerLines.push(line);
    }
  }

  if (currentApp) {
    sections.push({ app: currentApp.toLowerCase(), lines: trimSeparators(currentLines) });
  }

  return { headerLines: headerLines, sections: sections };
}

function trimSeparators(lines) {
  // Remove trailing --- and blank lines
  while (lines.length && (lines[lines.length - 1].trim() === "---" || lines[lines.length - 1].trim() === "")) {
    lines.pop();
  }
  return lines;
}

// --- Extract category sections ---

const CAT_HEADING = /^###\s+(.+)$/;
const CAT_MAP = {
  "features": "features",
  "bug fixes": "bug-fixes",
  "improvements": "improvements",
  "performance": "performance",
  "infrastructure": "infrastructure",
  "foundation": "features",
  "content": "features",
  "documentation": "improvements",
};

function extractCategorySections(content) {
  const lines = content.split("\n");
  const categories = {};
  let currentCat = null;
  let currentLines = [];

  for (const line of lines) {
    const catMatch = line.match(CAT_HEADING);
    if (catMatch) {
      if (currentCat) {
        if (!categories[currentCat]) categories[currentCat] = [];
        categories[currentCat].push(...trimSeparators(currentLines));
      }
      const catName = catMatch[1].trim().toLowerCase();
      currentCat = CAT_MAP[catName] || null;
      currentLines = currentCat ? [line] : [];
    } else if (currentCat) {
      currentLines.push(line);
    }
  }

  if (currentCat && currentLines.length) {
    if (!categories[currentCat]) categories[currentCat] = [];
    categories[currentCat].push(...trimSeparators(currentLines));
  }

  return categories;
}

// --- Generate pages ---

const APP_META = {
  api: { title: "API Releases", description: "Version history and changelog for the GAIA API backend, including new features, bug fixes, and performance improvements for each release.", icon: "server" },
  web: { title: "Web Releases", description: "Version history and changelog for the GAIA web application, including new features, bug fixes, and performance improvements for each release.", icon: "browser" },
  desktop: { title: "Desktop Releases", description: "Version history and changelog for the GAIA desktop app on macOS, Windows, and Linux, including features, bug fixes, and updates.", icon: "desktop" },
  mobile: { title: "Mobile Releases", description: "Version history and changelog for the GAIA mobile app, including new features, bug fixes, and performance improvements for each release.", icon: "mobile" },
  bots: { title: "Bots Releases", description: "Release history for GAIA's Discord, Slack, Telegram, and WhatsApp bots.", icon: "robot" },
  cli: { title: "CLI Releases", description: "Release history for the GAIA command-line interface.", icon: "terminal" },
};

const CATEGORY_META = {
  "features": { title: "Features", description: "A consolidated list of new features shipped across all GAIA releases, organized by version and platform.", icon: "sparkles" },
  "bug-fixes": { title: "Bug Fixes", description: "A consolidated list of bug fixes shipped across all GAIA releases, organized by version and platform.", icon: "bug" },
  "improvements": { title: "Improvements", description: "All improvements and enhancements shipped across GAIA releases.", icon: "arrow-up-right" },
  "performance": { title: "Performance", description: "All performance improvements shipped across GAIA releases.", icon: "gauge" },
};

const YEAR_DESCRIPTIONS = {
  "2025": "Complete changelog for GAIA in 2025, including the mobile app launch, desktop beta, and major API, web, and infrastructure updates.",
  "2026": "Complete changelog for GAIA in 2026, covering WhatsApp bot support, MCP Apps Builder, deep research, artifacts, and more across all platforms.",
};

function frontmatter(meta) {
  let fm = "---\n";
  fm += `title: "${meta.title}"\n`;
  fm += `description: "${meta.description}"\n`;
  if (meta.icon) fm += `icon: "${meta.icon}"\n`;
  fm += "---\n";
  return fm;
}

function wrapUpdate(label, description, innerContent) {
  const descAttr = description ? ` description="${description}"` : "";
  return `<Update label="${label}"${descAttr}>\n\n${innerContent}\n\n</Update>`;
}

function generateAppPages(blocks) {
  const appBlocks = {}; // app -> [{ label, description, content }]

  for (const block of blocks) {
    const { headerLines, sections } = extractAppSections(block.content);

    for (const section of sections) {
      if (!appBlocks[section.app]) appBlocks[section.app] = [];
      appBlocks[section.app].push({
        label: block.label,
        description: block.description,
        content: section.lines.join("\n"),
      });
    }

    // For legacy blocks (pre per-app era, no ## [App] headings), include in api and web
    if (sections.length === 0 && block.content.trim()) {
      for (const app of ["api", "web"]) {
        if (!appBlocks[app]) appBlocks[app] = [];
        appBlocks[app].push({
          label: block.label,
          description: block.description,
          content: block.content,
        });
      }
    }
  }

  for (const [app, meta] of Object.entries(APP_META)) {
    const entries = appBlocks[app] || [];
    if (entries.length === 0) continue;

    let mdx = frontmatter(meta) + "\n";
    mdx += entries.map(function (e) {
      return wrapUpdate(e.label, e.description, e.content);
    }).join("\n\n");
    mdx += "\n";

    fs.writeFileSync(path.join(OUT_DIR, `${app}.mdx`), mdx);
    console.log(`  ${app}.mdx (${entries.length} releases)`);
  }
}

function generateCategoryPages(blocks) {
  const APP_HEADING = /^## \[(\w+)\s+v[\d.]+\]/i;

  // For each category, collect per-release entries that show the app heading + bullet items (no category heading)
  const catBlocks = {}; // category -> [{ label, description, content }]

  for (const block of blocks) {
    const { sections } = extractAppSections(block.content);

    // Also handle legacy blocks (pre per-app era) where there are no ## [App] headings
    const legacyCategories = sections.length === 0 ? extractCategorySections(block.content) : {};

    // Per-app sections: collect each app's category content as a discrete block
    // so they can be joined with a blank-line separator regardless of source spacing.
    const catContent = {}; // cat -> array of per-app block strings

    for (const section of sections) {
      const lines = section.lines;
      let currentCat = null;
      let catLines = [];

      const flushCat = function () {
        if (currentCat && catLines.length) {
          if (!catContent[currentCat]) catContent[currentCat] = [];
          catContent[currentCat].push(trimSeparators(catLines).join("\n"));
        }
      };

      for (const line of lines) {
        const catMatch = line.match(CAT_HEADING);
        if (catMatch) {
          flushCat();
          const catName = catMatch[1].trim().toLowerCase();
          currentCat = CAT_MAP[catName] || null;
          // Start with the app heading (## [App vX.Y.Z]), skip the ### category heading
          catLines = currentCat ? [lines[0]] : []; // lines[0] is the ## heading
        } else if (currentCat) {
          catLines.push(line);
        }
      }

      flushCat();
    }

    // Add per-app category content to catBlocks, separating apps with a blank line
    for (const [cat, appBlockStrings] of Object.entries(catContent)) {
      if (!catBlocks[cat]) catBlocks[cat] = [];
      catBlocks[cat].push({
        label: block.label,
        description: block.description,
        content: appBlockStrings.join("\n\n"),
      });
    }

    // Add legacy (non per-app) category content — strip the ### heading, keep bullet items
    for (const [cat, lines] of Object.entries(legacyCategories)) {
      const filtered = lines.filter(function (l) { return !CAT_HEADING.test(l); });
      if (filtered.length === 0) continue;
      if (!catBlocks[cat]) catBlocks[cat] = [];
      catBlocks[cat].push({
        label: block.label,
        description: block.description,
        content: trimSeparators(filtered).join("\n"),
      });
    }
  }

  for (const [cat, meta] of Object.entries(CATEGORY_META)) {
    const entries = catBlocks[cat] || [];
    if (entries.length === 0) continue;

    let mdx = frontmatter(meta) + "\n";
    mdx += entries.map(function (e) {
      return wrapUpdate(e.label, e.description, e.content);
    }).join("\n\n");
    mdx += "\n";

    fs.writeFileSync(path.join(OUT_DIR, `${cat}.mdx`), mdx);
    console.log(`  ${cat}.mdx (${entries.length} releases)`);
  }
}

function generateYearPages(blocks) {
  const yearBlocks = {};

  for (const block of blocks) {
    if (!block.year) continue;
    if (!yearBlocks[block.year]) yearBlocks[block.year] = [];
    yearBlocks[block.year].push(block);
  }

  for (const [year, entries] of Object.entries(yearBlocks)) {
    const meta = {
      title: `${year} Releases`,
      description: YEAR_DESCRIPTIONS[year] || `All GAIA releases from ${year}.`,
      icon: "calendar",
    };

    let mdx = frontmatter(meta) + "\n";
    mdx += entries.map(function (e) {
      return wrapUpdate(e.label, e.description, e.content);
    }).join("\n\n");
    mdx += "\n";

    fs.writeFileSync(path.join(OUT_DIR, `${year}.mdx`), mdx);
    console.log(`  ${year}.mdx (${entries.length} releases)`);
  }
}

// --- Sync the page hero to the most recent release's image ---

function extractFirstImage(content) {
  // Markdown image: ![alt](src) ; HTML image: <img ... src="...">
  const md = content.match(/!\[[^\]]*\]\(([^)\s]+)\)/);
  const html = content.match(/<img[^>]+src="([^"]+)"/);
  if (md && html) {
    return content.indexOf(md[0]) <= content.indexOf(html[0]) ? md[1] : html[1];
  }
  return md ? md[1] : html ? html[1] : null;
}

function syncHeroImage(blocks) {
  if (blocks.length === 0) return;

  // blocks[0] is the most recent release (entries are newest-first).
  const latestImage = extractFirstImage(blocks[0].content);
  if (!latestImage) {
    console.log("  latest release has no image; page hero left unchanged");
    return;
  }

  const raw = fs.readFileSync(SOURCE, "utf-8");

  // The hero lives in the page header, before the first <Update> block.
  // Only the <img> there is rewritten, so per-release images are untouched.
  const firstUpdateIdx = raw.indexOf("<Update");
  if (firstUpdateIdx === -1) return;

  const head = raw.slice(0, firstUpdateIdx);
  const heroMatch = head.match(/<img[^>]+src="([^"]+)"/);
  if (!heroMatch) {
    console.log("  no <img> in page header; nothing to sync");
    return;
  }
  if (heroMatch[1] === latestImage) {
    console.log(`  page hero already current (${latestImage})`);
    return;
  }

  const updatedHead = head.replace(
    /(<img[^>]+src=")[^"]+("[^>]*>)/,
    `$1${latestImage}$2`,
  );
  fs.writeFileSync(SOURCE, updatedHead + raw.slice(firstUpdateIdx));
  console.log(`  page hero synced to ${latestImage}`);
}

// --- Main ---

function main() {
  console.log("Generating changelog sub-pages from release-notes.mdx...\n");

  if (!fs.existsSync(OUT_DIR)) {
    fs.mkdirSync(OUT_DIR, { recursive: true });
  }

  const blocks = parseSource();
  console.log(`Parsed ${blocks.length} release blocks.\n`);

  console.log("By App:");
  generateAppPages(blocks);

  console.log("\nBy Category:");
  generateCategoryPages(blocks);

  console.log("\nBy Year:");
  generateYearPages(blocks);

  console.log("\nHero:");
  syncHeroImage(blocks);

  console.log("\nDone.");
}

main();
