import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join, relative } from "node:path";
import { stripVTControlCharacters } from "node:util";
import { chromium } from "@playwright/test";

/**
 * Turn a visual-diff run (results.json) into summary.md, summary.json and one
 * base | head | diff composite PNG per changed surface.
 * Usage: node e2e/visual/compose.ts <out-dir> <base-label> <head-label>
 */

type Outcome = "unchanged" | "changed" | "new" | "failed" | "skipped";

interface Attachment {
  name: string;
  path?: string;
}

interface TestResult {
  status: string;
  attachments: Attachment[];
  errors: { message?: string }[];
}

interface Spec {
  title: string;
  tests: { results: TestResult[] }[];
}

interface Suite {
  specs?: Spec[];
  suites?: Suite[];
}

interface SurfaceResult {
  title: string;
  outcome: Outcome;
  diffRatio: number | null;
  sizeChange: string | null;
  error: string | null;
  composite: string | null;
  images: { base?: string; head?: string; diff?: string };
}

const COMPOSITE_COLUMN_PX = 720;

function* specsOf(suite: Suite): Generator<Spec> {
  yield* suite.specs ?? [];
  for (const child of suite.suites ?? []) yield* specsOf(child);
}

function attachmentPath(
  result: TestResult,
  suffix: string,
): string | undefined {
  return result.attachments.find((a) => a.name.endsWith(suffix))?.path;
}

// PNG stores width and height as big-endian uint32s at bytes 16 and 20.
function pngArea(path: string): number {
  const header = readFileSync(path).subarray(16, 24);
  return header.readUInt32BE(0) * header.readUInt32BE(4);
}

function classify(spec: Spec): SurfaceResult {
  const result = spec.tests[0]?.results.at(-1);
  if (!result) throw new Error(`no result recorded for ${spec.title}`);
  const message = stripVTControlCharacters(
    result.errors.map((e) => e.message ?? "").join("\n"),
  );
  const images = {
    base: attachmentPath(result, "-expected.png"),
    head: attachmentPath(result, "-actual.png"),
    diff: attachmentPath(result, "-diff.png"),
  };
  // Playwright rounds its ratio to 0.01, so derive it from the exact pixel count.
  const changedPixels = message.match(/(\d+) pixels \(ratio/);
  const size = message.match(
    /Expected an image (\d+)px by (\d+)px, received (\d+)px by (\d+)px/,
  );
  let outcome: Outcome;
  if (result.status === "passed") outcome = "unchanged";
  else if (result.status === "skipped") outcome = "skipped";
  else if (message.includes("A snapshot doesn't exist")) outcome = "new";
  else if (images.base && images.head) outcome = "changed";
  else outcome = "failed";
  return {
    title: spec.title,
    outcome,
    diffRatio:
      changedPixels && images.head
        ? Number(changedPixels[1]) / pngArea(images.head)
        : null,
    sizeChange: size ? `${size[1]}x${size[2]} → ${size[3]}x${size[4]}` : null,
    error: outcome === "failed" ? message.split("\n")[0] : null,
    composite: null,
    images,
  };
}

// Inline the PNGs: a setContent page is about:blank and cannot load file:// images.
function dataUri(path: string): string {
  return `data:image/png;base64,${readFileSync(path).toString("base64")}`;
}

function compositeHtml(
  item: SurfaceResult,
  baseLabel: string,
  headLabel: string,
): string {
  const column = (label: string, path: string | undefined) =>
    `<figure><figcaption>${label}</figcaption>${
      path ? `<img src="${dataUri(path)}">` : "<p>none</p>"
    }</figure>`;
  return `<!doctype html><html><head><style>
    body{margin:0;padding:16px;background:#18181b;color:#e4e4e7;font:14px system-ui}
    h1{font-size:16px;margin:0 0 12px}
    main{display:flex;gap:12px;align-items:flex-start}
    figure{margin:0;width:${COMPOSITE_COLUMN_PX}px}
    figcaption{margin-bottom:6px;color:#a1a1aa}
    img{width:100%;display:block;background:#000}
  </style></head><body><h1>${item.title}</h1><main>${column(
    `Before · ${baseLabel}`,
    item.images.base,
  )}${column(`After · ${headLabel}`, item.images.head)}${column(
    "Changed pixels",
    item.images.diff,
  )}</main></body></html>`;
}

function summaryMarkdown(
  items: SurfaceResult[],
  outDir: string,
  baseLabel: string,
  headLabel: string,
): string {
  const count = (outcome: Outcome) =>
    items.filter((i) => i.outcome === outcome).length;
  const changed = items
    .filter((i) => i.outcome === "changed")
    .sort((a, b) => (b.diffRatio ?? 1) - (a.diffRatio ?? 1));
  const rows = changed.map((i) => {
    const ratio =
      i.diffRatio === null
        ? "size changed"
        : `${(i.diffRatio * 100).toFixed(2)}%`;
    const link = i.composite
      ? `[composite](${relative(outDir, i.composite)})`
      : "";
    return `| \`${i.title}\` | ${ratio} | ${i.sizeChange ?? ""} | ${link} |`;
  });
  const listed = (outcome: Outcome) =>
    items
      .filter((i) => i.outcome === outcome)
      .map((i) => `- \`${i.title}\`${i.error ? ` — ${i.error}` : ""}`)
      .join("\n") || "- none";
  return [
    `# Visual diff: ${baseLabel} → ${headLabel}`,
    "",
    `${items.length} surfaces · ${count("changed")} changed · ${count("unchanged")} unchanged · ${count("new")} new · ${count("failed")} failed · ${count("skipped")} skipped (redirect off-site)`,
    "",
    "## Changed (largest first)",
    "",
    "| Surface | Pixels changed | Size | Composite |",
    "| --- | --- | --- | --- |",
    ...rows,
    "",
    "## New on head (no base render)",
    "",
    listed("new"),
    "",
    "## Failed to render",
    "",
    listed("failed"),
    "",
    "## Skipped (redirect off-site, not our UI)",
    "",
    listed("skipped"),
    "",
  ].join("\n");
}

async function main(): Promise<void> {
  const [outDir, baseLabel = "base", headLabel = "head"] =
    process.argv.slice(2);
  if (!outDir)
    throw new Error("usage: compose.ts <out-dir> [base-label] [head-label]");
  const report = JSON.parse(
    readFileSync(join(outDir, "results.json"), "utf8"),
  ) as Suite;
  const items = [...specsOf(report)].map(classify);

  const compositeDir = join(outDir, "composites");
  mkdirSync(compositeDir, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: COMPOSITE_COLUMN_PX * 3 + 56, height: 800 },
  });
  for (const item of items.filter((i) => i.outcome === "changed")) {
    await page.setContent(compositeHtml(item, baseLabel, headLabel), {
      waitUntil: "load",
    });
    item.composite = join(
      compositeDir,
      basename(item.images.head ?? `${item.title}.png`),
    );
    await page.screenshot({ path: item.composite, fullPage: true });
  }
  await browser.close();

  writeFileSync(join(outDir, "summary.json"), JSON.stringify(items, null, 2));
  writeFileSync(
    join(outDir, "summary.md"),
    summaryMarkdown(items, outDir, baseLabel, headLabel),
  );
  console.info(readFileSync(join(outDir, "summary.md"), "utf8").split("\n")[2]);
}

await main();
