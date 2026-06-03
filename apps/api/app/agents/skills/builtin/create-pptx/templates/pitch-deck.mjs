// PITCH-DECK TEMPLATE (pptxgenjs, ESM) — benchmark-quality startup fundraising deck.
//
// Purpose & style differ deliberately from `deck.mjs` (a corporate quarterly
// review): this is an investor PITCH — bolder type, a dark "founder" palette,
// a teal/coral accent system, and a narrative arc (problem → solution → market
// → traction → ask). Adapt the CONTENT arrays and PALETTE consts; keep the
// layout grid and the contract below intact.
//
// CONTRACT
//   • Run:  node pitch-deck.mjs out.pptx   (with `pptxgenjs` resolvable)
//   • Writes to process.argv[2] (fallback "out.pptx") via `await pptx.writeFile`.
//   • LAYOUT_WIDE → 13.33in × 7.5in. Keep every element inside those bounds.
//   • No external image/asset files — every graphic is a pptxgenjs SHAPE.
//
// RENDERING RULES (hard-won — do NOT regress):
//   • NO `addChart`. Native OOXML charts render BLANK in macOS Keynote / Quick
//     Look. Every chart here is hand-drawn from rects/lines/ellipses so it
//     renders identically everywhere.
//   • Font is the cross-platform "Arial" (bold via `bold:true`). Never
//     "Segoe UI" / "Segoe UI Semibold" — those trigger a missing-font warning
//     and substitution on macOS.
//   • No empty slides — every slide carries visible body content.
import pptxgen from "pptxgenjs";

// ---------------------------------------------------------------------------
// PALETTE & TYPE TOKENS — single source of truth for branding.
// Colors are 6-digit hex strings WITHOUT a leading "#", as pptxgenjs expects.
// ---------------------------------------------------------------------------
const COLOR = {
  bg: "0B1020", // deep navy — primary dark backdrop
  bgAlt: "121A33", // slightly lifted navy for panels on dark
  ink: "0B1020", // near-black for text on light slides
  body: "44506B", // muted slate body text on light
  faint: "8A93A8", // captions / footer / axis labels
  line: "DDE3EE", // hairline borders on light
  panel: "F5F7FC", // light card fill
  teal: "16C2A3", // primary accent (brand)
  tealDk: "0E8C77", // darker teal for depth
  coral: "FF6B5C", // secondary accent / "problem" red-orange
  gold: "F6C453", // tertiary highlight
  white: "FFFFFF",
  mist: "B9C2D6", // light text on dark backdrops
};

// Slide geometry (inches) for the widescreen layout.
const PAGE = { w: 13.33, h: 7.5, margin: 0.65 };
const CONTENT_W = PAGE.w - PAGE.margin * 2; // 12.03in usable width

// Single cross-platform font face. Bold is applied per-run via `bold:true`.
const FONT = "Arial";

// Brand identity reused across slides.
const BRAND = { name: "Nimbus", tag: "Ship infra in a click" };

// ---------------------------------------------------------------------------
// PRESENTATION SETUP
// ---------------------------------------------------------------------------
const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "GAIA";
pptx.company = BRAND.name;
pptx.subject = "Seed Pitch Deck";
pptx.title = `${BRAND.name} — Seed Round`;

// ---------------------------------------------------------------------------
// SLIDE MASTER — light content slides inherit a footer rule + slide number.
// Dark "moment" slides (cover, dividers, closing) skip the master for a
// full-bleed look. `slideNumber` renders the running page number.
// ---------------------------------------------------------------------------
const MASTER = "PITCH";
pptx.defineSlideMaster({
  title: MASTER,
  background: { color: COLOR.white },
  objects: [
    // footer hairline
    { line: { x: PAGE.margin, y: 7.04, w: CONTENT_W, h: 0, line: { color: COLOR.line, width: 0.75 } } },
    // footer label (left)
    {
      text: {
        text: `${BRAND.name}  ·  Confidential`,
        options: { x: PAGE.margin, y: 7.08, w: 8.5, h: 0.3, fontSize: 9, color: COLOR.faint, fontFace: FONT, align: "left", valign: "middle" },
      },
    },
  ],
  // running slide number, bottom-right
  slideNumber: { x: 12.25, y: 7.08, w: 0.6, h: 0.3, fontSize: 9, color: COLOR.faint, fontFace: FONT, align: "right" },
});

// ---------------------------------------------------------------------------
// HELPERS — small, composable builders so each slide reads declaratively.
// ---------------------------------------------------------------------------

// Standard content-slide header: a teal kicker (eyebrow) + bold title, with a
// short teal underline rule for a consistent "brand mark" on every slide.
const addHeader = (slide, title, kicker) => {
  if (kicker) {
    slide.addText(kicker.toUpperCase(), {
      x: PAGE.margin, y: 0.46, w: CONTENT_W, h: 0.3,
      fontSize: 12, bold: true, color: COLOR.teal, charSpacing: 3, fontFace: FONT,
    });
  }
  slide.addText(title, {
    x: PAGE.margin, y: kicker ? 0.74 : 0.55, w: CONTENT_W, h: 0.72,
    fontSize: 30, bold: true, color: COLOR.ink, fontFace: FONT, align: "left", valign: "middle",
  });
  // short brand underline beneath the title
  slide.addShape(pptx.ShapeType.rect, { x: PAGE.margin, y: kicker ? 1.5 : 1.32, w: 0.9, h: 0.06, fill: { color: COLOR.teal } });
};

// Small lozenge "logo" mark (rounded square + initial) reused on dark slides.
const addLogoMark = (slide, x, y, size = 0.5) => {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w: size, h: size, rectRadius: size * 0.28, fill: { color: COLOR.teal } });
  slide.addText(BRAND.name.charAt(0), { x, y, w: size, h: size, fontSize: 22, bold: true, color: COLOR.bg, align: "center", valign: "middle", fontFace: FONT });
};

// ===========================================================================
// SLIDE 1 — COVER (full-bleed dark; company + tagline)
// Layered accent shapes give depth without any image asset.
// ===========================================================================
let s = pptx.addSlide();
s.background = { color: COLOR.bg };
// decorative oversized accent rings drawn as outlined ellipses (top-right)
s.addShape(pptx.ShapeType.ellipse, { x: 9.7, y: -1.6, w: 5.4, h: 5.4, fill: { type: "none" }, line: { color: COLOR.tealDk, width: 1.25 } });
s.addShape(pptx.ShapeType.ellipse, { x: 10.7, y: -0.6, w: 3.4, h: 3.4, fill: { type: "none" }, line: { color: COLOR.coral, width: 1.25 } });
// left accent bar
s.addShape(pptx.ShapeType.rect, { x: 0, y: 2.95, w: 0.2, h: 1.95, fill: { color: COLOR.teal } });
// logo mark + wordmark
addLogoMark(s, 0.85, 0.85, 0.62);
s.addText(BRAND.name, { x: 1.6, y: 0.85, w: 6, h: 0.62, fontSize: 24, bold: true, color: COLOR.white, valign: "middle", fontFace: FONT });
// headline tagline
s.addText("Cloud infrastructure,\nin a single click.", {
  x: 0.82, y: 2.85, w: 9.2, h: 2.1, fontSize: 50, bold: true, color: COLOR.white, fontFace: FONT, lineSpacingMultiple: 1.02,
});
s.addText("The deploy platform for teams that would rather build product than babysit YAML.", {
  x: 0.85, y: 5.05, w: 8.4, h: 0.7, fontSize: 18, color: COLOR.mist, fontFace: FONT,
});
// footer line: round + stage tag
s.addText(
  [
    { text: "Seed Round 2026", options: { bold: true, color: COLOR.teal } },
    { text: "      ·      Confidential", options: { color: COLOR.faint } },
  ],
  { x: 0.85, y: 6.55, w: 11, h: 0.5, fontSize: 14, fontFace: FONT },
);

// ===========================================================================
// SLIDE 2 — THE PROBLEM
// A bold pain statement + three "friction" cards drawn as rounded panels.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Shipping infrastructure is still painful", "The problem");
s.addText("Every team rebuilds the same deploy plumbing — and loses weeks doing it.", {
  x: PAGE.margin, y: 1.72, w: CONTENT_W, h: 0.6, fontSize: 18, color: COLOR.body, fontFace: FONT,
});
const problems = [
  { stat: "3 wks", t: "Setup tax", d: "Average time a new team spends wiring CI/CD, secrets, and networking before line one of product." },
  { stat: "60%", t: "Ops drag", d: "Of engineering time at growth-stage startups is spent maintaining infra, not building features." },
  { stat: "$140k", t: "Hidden cost", d: "Annual fully-loaded cost of the dedicated DevOps hire most 10-person teams are forced into too early." },
];
const probW = (CONTENT_W - 0.5 * (problems.length - 1)) / problems.length;
problems.forEach((p, i) => {
  const x = PAGE.margin + i * (probW + 0.5);
  s.addShape(pptx.ShapeType.roundRect, { x, y: 2.55, w: probW, h: 3.9, rectRadius: 0.14, fill: { color: COLOR.panel }, line: { color: COLOR.line, width: 1 } });
  // coral top accent stripe signals "pain"
  s.addShape(pptx.ShapeType.rect, { x, y: 2.55, w: probW, h: 0.14, fill: { color: COLOR.coral } });
  s.addText(p.stat, { x: x + 0.25, y: 2.85, w: probW - 0.5, h: 1.1, fontSize: 44, bold: true, color: COLOR.coral, valign: "middle", fontFace: FONT });
  s.addText(p.t, { x: x + 0.25, y: 4.0, w: probW - 0.5, h: 0.5, fontSize: 18, bold: true, color: COLOR.ink, fontFace: FONT });
  s.addText(p.d, { x: x + 0.25, y: 4.55, w: probW - 0.5, h: 1.7, fontSize: 13.5, color: COLOR.body, fontFace: FONT, lineSpacingMultiple: 1.25, valign: "top" });
});

// ===========================================================================
// SLIDE 3 — THE SOLUTION
// Left: bold one-liner + supporting bullets. Right: a drawn "flow" of three
// chips (Connect → Deploy → Scale) joined by arrow shapes — no image asset.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "One platform. Zero plumbing.", "The solution");
s.addText("Nimbus turns a repo into production infrastructure automatically — sane defaults, no config.", {
  x: PAGE.margin, y: 1.72, w: 6.1, h: 1.0, fontSize: 18, color: COLOR.body, fontFace: FONT, lineSpacingMultiple: 1.25,
});
s.addText(
  [
    { text: "Push a repo, get a live URL in 90 seconds", options: { bullet: { code: "2713" }, color: COLOR.ink, bold: true } },
    { text: "CI/CD, secrets, and scaling handled for you", options: { bullet: { code: "2713" }, color: COLOR.ink, bold: true } },
    { text: "Pay for usage, not idle capacity", options: { bullet: { code: "2713" }, color: COLOR.ink, bold: true } },
    { text: "Escape hatches when you outgrow the defaults", options: { bullet: { code: "2713" }, color: COLOR.ink, bold: true } },
  ],
  { x: PAGE.margin, y: 2.9, w: 6.0, h: 3.4, fontSize: 16, color: COLOR.ink, fontFace: FONT, lineSpacingMultiple: 1.4, paraSpaceAfter: 10, valign: "top" },
);
// right-side flow of three stage chips
const flow = [
  { t: "Connect", d: "Link your repo", c: COLOR.teal },
  { t: "Deploy", d: "Auto-build + ship", c: COLOR.tealDk },
  { t: "Scale", d: "Usage-based autoscale", c: COLOR.gold },
];
const flowX = 7.15;
const flowW = 4.85;
flow.forEach((f, i) => {
  const y = 2.05 + i * 1.55;
  s.addShape(pptx.ShapeType.roundRect, { x: flowX, y, w: flowW, h: 1.15, rectRadius: 0.12, fill: { color: COLOR.bgAlt } });
  s.addShape(pptx.ShapeType.rect, { x: flowX, y: y + 0.18, w: 0.12, h: 0.79, fill: { color: f.c } });
  s.addText(`${i + 1}`, { x: flowX + 0.25, y, w: 0.7, h: 1.15, fontSize: 30, bold: true, color: f.c, align: "center", valign: "middle", fontFace: FONT });
  s.addText(f.t, { x: flowX + 1.05, y: y + 0.18, w: flowW - 1.2, h: 0.45, fontSize: 18, bold: true, color: COLOR.white, valign: "middle", fontFace: FONT });
  s.addText(f.d, { x: flowX + 1.05, y: y + 0.62, w: flowW - 1.2, h: 0.4, fontSize: 13, color: COLOR.mist, valign: "middle", fontFace: FONT });
  // down arrow connector between chips
  if (i < flow.length - 1) {
    s.addShape(pptx.ShapeType.downArrow, { x: flowX + flowW / 2 - 0.18, y: y + 1.16, w: 0.36, h: 0.36, fill: { color: COLOR.line } });
  }
});

// ===========================================================================
// SLIDE 4 — PRODUCT (feature highlight cards, 2×2 grid)
// Each card: drawn icon glyph (rounded square + symbol shape) + title + copy.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "What you get", "Product");
const features = [
  { t: "Instant deploys", d: "Git push to live URL in under two minutes, with automatic preview environments per PR." },
  { t: "Managed data", d: "Postgres, Redis, and object storage provisioned and backed up — no console clicking." },
  { t: "Usage autoscaling", d: "Scale to zero when idle, burst on demand. You only pay for the requests you serve." },
  { t: "Built-in observability", d: "Logs, metrics, and traces wired on day one, with alerting that ships by default." },
];
const fcW = (CONTENT_W - 0.5) / 2;
const fcH = 2.25;
features.forEach((f, i) => {
  const col = i % 2;
  const row = Math.floor(i / 2);
  const x = PAGE.margin + col * (fcW + 0.5);
  const y = 1.9 + row * (fcH + 0.4);
  s.addShape(pptx.ShapeType.roundRect, { x, y, w: fcW, h: fcH, rectRadius: 0.14, fill: { color: COLOR.panel }, line: { color: COLOR.line, width: 1 } });
  // drawn "icon": teal rounded square with a small white dot+bar glyph
  s.addShape(pptx.ShapeType.roundRect, { x: x + 0.3, y: y + 0.32, w: 0.7, h: 0.7, rectRadius: 0.16, fill: { color: COLOR.teal } });
  s.addShape(pptx.ShapeType.ellipse, { x: x + 0.46, y: y + 0.46, w: 0.18, h: 0.18, fill: { color: COLOR.white } });
  s.addShape(pptx.ShapeType.rect, { x: x + 0.42, y: y + 0.74, w: 0.46, h: 0.12, fill: { color: COLOR.white } });
  s.addText(f.t, { x: x + 1.2, y: y + 0.3, w: fcW - 1.45, h: 0.55, fontSize: 19, bold: true, color: COLOR.ink, valign: "middle", fontFace: FONT });
  s.addText(f.d, { x: x + 1.2, y: y + 0.9, w: fcW - 1.45, h: 1.1, fontSize: 13.5, color: COLOR.body, fontFace: FONT, lineSpacingMultiple: 1.25, valign: "top" });
});

// ===========================================================================
// SLIDE 5 — MARKET SIZE (TAM / SAM / SOM as drawn concentric circles)
// Concentric ellipses (largest behind) with leader labels — fully drawn.
// A right-side legend lists the dollar figures.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "A large, expanding market", "Market size");
// concentric circles centered on the left half
const cx = 3.85; // center x of the largest circle
const market = [
  { label: "TAM", value: "$84B", d: "Global cloud platform spend", dia: 4.4, color: COLOR.bgAlt, txt: COLOR.white },
  { label: "SAM", value: "$19B", d: "Self-serve PaaS for SMB/startups", dia: 3.0, color: COLOR.tealDk, txt: COLOR.white },
  { label: "SOM", value: "$640M", d: "Reachable in 5 yrs", dia: 1.6, color: COLOR.teal, txt: COLOR.bg },
];
// draw largest first so smaller sit on top; bottom-aligned so circles nest
const baseBottom = 6.55;
market.forEach((m) => {
  const x = cx - m.dia / 2;
  const y = baseBottom - m.dia;
  s.addShape(pptx.ShapeType.ellipse, { x, y, w: m.dia, h: m.dia, fill: { color: m.color } });
});
// labels inside each ring (stacked near the top of each band)
s.addText([{ text: "TAM ", options: { bold: true } }, { text: "$84B", options: { bold: true, color: COLOR.teal } }], { x: cx - 1.6, y: 2.4, w: 3.2, h: 0.45, fontSize: 18, color: COLOR.white, align: "center", fontFace: FONT });
s.addText([{ text: "SAM ", options: { bold: true } }, { text: "$19B", options: { bold: true, color: COLOR.gold } }], { x: cx - 1.4, y: 3.85, w: 2.8, h: 0.45, fontSize: 17, color: COLOR.white, align: "center", fontFace: FONT });
s.addText([{ text: "SOM ", options: { bold: true } }, { text: "$640M", options: { bold: true } }], { x: cx - 1.0, y: 5.2, w: 2.0, h: 0.45, fontSize: 15, color: COLOR.bg, align: "center", fontFace: FONT });
// right-side legend with descriptions
const legX = 7.4;
market.forEach((m, i) => {
  const y = 2.55 + i * 1.25;
  s.addShape(pptx.ShapeType.rect, { x: legX, y: y + 0.06, w: 0.32, h: 0.32, fill: { color: m.color === COLOR.bgAlt ? COLOR.body : m.color } });
  s.addText([{ text: `${m.label}  `, options: { bold: true, color: COLOR.ink } }, { text: m.value, options: { bold: true, color: COLOR.teal } }], { x: legX + 0.5, y, w: 4.6, h: 0.45, fontSize: 20, fontFace: FONT });
  s.addText(m.d, { x: legX + 0.5, y: y + 0.46, w: 4.6, h: 0.5, fontSize: 13.5, color: COLOR.body, fontFace: FONT });
});

// ===========================================================================
// SLIDE 6 — BUSINESS MODEL
// Three pricing tiers as cards + a one-line revenue logic strip beneath.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "How we make money", "Business model");
const tiers = [
  { name: "Hobby", price: "$0", sub: "/mo", d: "Free tier to drive bottom-up adoption", points: ["1 project", "Community support"], featured: false },
  { name: "Pro", price: "$29", sub: "/seat/mo", d: "Self-serve sweet spot for small teams", points: ["Unlimited projects", "Usage-based compute", "Email support"], featured: true },
  { name: "Scale", price: "Custom", sub: "", d: "Committed-use contracts for larger orgs", points: ["SSO + audit logs", "SLA + dedicated support"], featured: false },
];
const tW = (CONTENT_W - 0.5 * (tiers.length - 1)) / tiers.length;
tiers.forEach((t, i) => {
  const x = PAGE.margin + i * (tW + 0.5);
  const featured = t.featured;
  s.addShape(pptx.ShapeType.roundRect, { x, y: 1.85, w: tW, h: 3.7, rectRadius: 0.14, fill: { color: featured ? COLOR.bgAlt : COLOR.panel }, line: { color: featured ? COLOR.teal : COLOR.line, width: featured ? 2 : 1 } });
  if (featured) {
    // "Most popular" ribbon chip
    s.addShape(pptx.ShapeType.roundRect, { x: x + tW - 1.85, y: 1.6, w: 1.7, h: 0.42, rectRadius: 0.2, fill: { color: COLOR.teal } });
    s.addText("MOST POPULAR", { x: x + tW - 1.85, y: 1.6, w: 1.7, h: 0.42, fontSize: 9, bold: true, color: COLOR.bg, align: "center", valign: "middle", charSpacing: 1, fontFace: FONT });
  }
  const tc = featured ? COLOR.white : COLOR.ink;
  const bc = featured ? COLOR.mist : COLOR.body;
  s.addText(t.name, { x: x + 0.3, y: 2.1, w: tW - 0.6, h: 0.5, fontSize: 18, bold: true, color: featured ? COLOR.teal : COLOR.ink, fontFace: FONT });
  s.addText([{ text: t.price, options: { bold: true, fontSize: 36, color: tc } }, { text: t.sub, options: { fontSize: 14, color: bc } }], { x: x + 0.3, y: 2.55, w: tW - 0.6, h: 0.8, fontFace: FONT, valign: "middle" });
  s.addText(t.d, { x: x + 0.3, y: 3.4, w: tW - 0.6, h: 0.65, fontSize: 12.5, color: bc, fontFace: FONT, lineSpacingMultiple: 1.2 });
  s.addText(
    t.points.map((p) => ({ text: p, options: { bullet: { code: "2713" }, color: tc } })),
    { x: x + 0.4, y: 4.1, w: tW - 0.7, h: 1.3, fontSize: 12.5, fontFace: FONT, lineSpacingMultiple: 1.25, paraSpaceAfter: 4, valign: "top" },
  );
});
// revenue logic strip
s.addShape(pptx.ShapeType.roundRect, { x: PAGE.margin, y: 5.8, w: CONTENT_W, h: 0.95, rectRadius: 0.12, fill: { color: COLOR.panel }, line: { color: COLOR.line, width: 1 } });
s.addText(
  [
    { text: "Land bottom-up free ", options: { bold: true, color: COLOR.ink } },
    { text: "→ convert to Pro seats → expand on usage → upsell Scale contracts.", options: { color: COLOR.body } },
  ],
  { x: PAGE.margin + 0.3, y: 5.8, w: CONTENT_W - 0.6, h: 0.95, fontSize: 16, valign: "middle", fontFace: FONT },
);

// ===========================================================================
// SLIDE 7 — TRACTION (drawn growth bar chart + KPI cards)
// Left: hand-drawn column chart of ARR (rects scaled to value). Right: KPI
// stat cards. No addChart — bars are pure shapes with value labels on top.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "The line goes up", "Traction");
// --- drawn column chart (left) ---
const chart = { x: PAGE.margin, y: 2.0, w: 6.6, h: 4.4 };
const arr = [
  { label: "Q1", v: 120 },
  { label: "Q2", v: 210 },
  { label: "Q3", v: 360 },
  { label: "Q4", v: 540 },
  { label: "Q1+1", v: 820 },
];
const maxV = 900; // axis ceiling, slightly above the tallest bar
const axisY = chart.y + chart.h - 0.55; // baseline y (leave room for labels)
const plotH = chart.h - 0.85; // vertical space for bars
const plotTop = chart.y + 0.3;
// baseline + faint gridlines (drawn lines)
s.addShape(pptx.ShapeType.line, { x: chart.x, y: axisY, w: chart.w, h: 0, line: { color: COLOR.faint, width: 1 } });
[0.25, 0.5, 0.75, 1].forEach((g) => {
  const gy = axisY - plotH * g;
  s.addShape(pptx.ShapeType.line, { x: chart.x, y: gy, w: chart.w, h: 0, line: { color: COLOR.line, width: 0.5 } });
});
const slotW = chart.w / arr.length;
const barW = slotW * 0.5;
arr.forEach((d, i) => {
  const h = (d.v / maxV) * plotH;
  const bx = chart.x + i * slotW + (slotW - barW) / 2;
  const by = axisY - h;
  // last bar (projection) drawn in gold to signal forecast vs. actual teal
  const isLast = i === arr.length - 1;
  s.addShape(pptx.ShapeType.roundRect, { x: bx, y: by, w: barW, h, rectRadius: 0.06, fill: { color: isLast ? COLOR.gold : COLOR.teal } });
  // value label above bar
  s.addText(`$${d.v}k`, { x: bx - 0.25, y: by - 0.42, w: barW + 0.5, h: 0.35, fontSize: 12, bold: true, color: COLOR.ink, align: "center", fontFace: FONT });
  // category label below baseline
  s.addText(d.label, { x: bx - 0.25, y: axisY + 0.08, w: barW + 0.5, h: 0.35, fontSize: 12, color: COLOR.body, align: "center", fontFace: FONT });
});
s.addText("ARR ($k) — last 4 quarters + next-quarter projection (gold)", { x: chart.x, y: plotTop - 0.32, w: chart.w, h: 0.3, fontSize: 12, italic: true, color: COLOR.faint, fontFace: FONT });
// --- KPI cards (right) ---
const kpis = [
  { v: "$540k", l: "ARR", delta: "+157% YoY" },
  { v: "1,240", l: "Paying teams", delta: "+38% QoQ" },
  { v: "129%", l: "Net revenue retention", delta: "+7 pts" },
  { v: "4.1%", l: "Free → paid conversion", delta: "+0.9 pts" },
];
const kx = 7.5;
const kW = (CONTENT_W - (kx - PAGE.margin) - 0.4) / 2;
const kH = 1.95;
kpis.forEach((k, i) => {
  const col = i % 2;
  const row = Math.floor(i / 2);
  const x = kx + col * (kW + 0.4);
  const y = 2.0 + row * (kH + 0.4);
  s.addShape(pptx.ShapeType.roundRect, { x, y, w: kW, h: kH, rectRadius: 0.12, fill: { color: COLOR.panel }, line: { color: COLOR.line, width: 1 } });
  s.addShape(pptx.ShapeType.rect, { x, y, w: kW, h: 0.1, fill: { color: COLOR.teal } });
  s.addText(k.v, { x: x + 0.2, y: y + 0.2, w: kW - 0.4, h: 0.8, fontSize: 30, bold: true, color: COLOR.ink, valign: "middle", fontFace: FONT });
  s.addText(k.l, { x: x + 0.2, y: y + 1.0, w: kW - 0.4, h: 0.4, fontSize: 12.5, color: COLOR.body, fontFace: FONT });
  s.addText(k.delta, { x: x + 0.2, y: y + 1.42, w: kW - 0.4, h: 0.4, fontSize: 12.5, bold: true, color: COLOR.tealDk, fontFace: FONT });
});

// ===========================================================================
// SLIDE 8 — COMPETITION (drawn 2×2 positioning matrix)
// Two axes drawn as lines, quadrant labels, and dots for each player; Nimbus
// sits in the desirable top-right. Fully drawn — no chart, no image.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Where we win", "Competition");
// matrix plot area
const mx = PAGE.margin + 0.4;
const my = 2.0;
const mw = 7.4;
const mh = 4.3;
// outer frame
s.addShape(pptx.ShapeType.rect, { x: mx, y: my, w: mw, h: mh, fill: { color: COLOR.panel }, line: { color: COLOR.line, width: 1 } });
// axes (mid lines)
s.addShape(pptx.ShapeType.line, { x: mx, y: my + mh / 2, w: mw, h: 0, line: { color: COLOR.faint, width: 1, dashType: "dash" } });
s.addShape(pptx.ShapeType.line, { x: mx + mw / 2, y: my, w: 0, h: mh, line: { color: COLOR.faint, width: 1, dashType: "dash" } });
// axis labels
s.addText("Easy to use →", { x: mx, y: my + mh + 0.08, w: mw, h: 0.3, fontSize: 12, bold: true, color: COLOR.body, align: "center", fontFace: FONT });
s.addText("Powerful →", { x: mx - 1.85, y: my + mh / 2 - 0.15, w: 2.0, h: 0.3, fontSize: 12, bold: true, color: COLOR.body, align: "center", rotate: 270, fontFace: FONT });
// players: px/py are 0..1 within the plot; Nimbus is the highlighted dot
const players = [
  { n: "Legacy cloud", px: 0.2, py: 0.78, c: COLOR.faint, big: false },
  { n: "DIY / K8s", px: 0.16, py: 0.3, c: COLOR.faint, big: false },
  { n: "Old PaaS", px: 0.7, py: 0.32, c: COLOR.coral, big: false },
  { n: BRAND.name, px: 0.78, py: 0.8, c: COLOR.teal, big: true },
];
players.forEach((p) => {
  const dia = p.big ? 0.55 : 0.32;
  const dotX = mx + p.px * mw - dia / 2;
  const dotY = my + (1 - p.py) * mh - dia / 2; // invert: higher py = higher on slide
  s.addShape(pptx.ShapeType.ellipse, { x: dotX, y: dotY, w: dia, h: dia, fill: { color: p.c }, line: p.big ? { color: COLOR.white, width: 2 } : undefined });
  s.addText(p.n, { x: dotX - 0.9, y: dotY + dia + 0.02, w: dia + 1.8, h: 0.3, fontSize: p.big ? 13 : 11, bold: p.big, color: p.big ? COLOR.teal : COLOR.body, align: "center", fontFace: FONT });
});
// right-side "why we win" bullets
s.addText("Why Nimbus wins", { x: 8.7, y: 2.0, w: 3.95, h: 0.4, fontSize: 16, bold: true, color: COLOR.ink, fontFace: FONT });
s.addText(
  [
    { text: "Powerful defaults without the K8s tax", options: { bullet: { code: "2713" }, color: COLOR.ink } },
    { text: "Usage pricing undercuts legacy by ~40%", options: { bullet: { code: "2713" }, color: COLOR.ink } },
    { text: "Self-serve onboarding, no sales call", options: { bullet: { code: "2713" }, color: COLOR.ink } },
    { text: "Escape hatches keep power users in", options: { bullet: { code: "2713" }, color: COLOR.ink } },
  ],
  { x: 8.7, y: 2.55, w: 3.95, h: 3.6, fontSize: 14, fontFace: FONT, lineSpacingMultiple: 1.35, paraSpaceAfter: 8, valign: "top" },
);

// ===========================================================================
// SLIDE 9 — GO-TO-MARKET (three-phase motion as a drawn horizontal pipeline)
// Stage chips joined by right arrows; each phase has a focus + a target metric.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "Land bottom-up, expand top-down", "Go-to-market");
const gtm = [
  { phase: "Now", t: "Developer-led", d: "Free tier + content + open-source plugins drive self-serve signups.", metric: "PLG funnel", c: COLOR.teal },
  { phase: "6–12 mo", t: "Team expansion", d: "In-product upgrade prompts and seat-based growth inside accounts.", metric: "Net expansion", c: COLOR.tealDk },
  { phase: "12–24 mo", t: "Enterprise motion", d: "Sales-assist for Scale contracts, SSO, and compliance buyers.", metric: "ACV growth", c: COLOR.gold },
];
const gW = 3.55;
const gGap = (CONTENT_W - gW * gtm.length) / (gtm.length - 1);
const gY = 2.4;
gtm.forEach((g, i) => {
  const x = PAGE.margin + i * (gW + gGap);
  if (i > 0) {
    s.addShape(pptx.ShapeType.rightArrow, { x: x - gGap - 0.02, y: gY + 1.4, w: gGap + 0.04, h: 0.4, fill: { color: COLOR.line } });
  }
  s.addShape(pptx.ShapeType.roundRect, { x, y: gY, w: gW, h: 3.3, rectRadius: 0.14, fill: { color: COLOR.panel }, line: { color: COLOR.line, width: 1 } });
  s.addShape(pptx.ShapeType.roundRect, { x, y: gY, w: gW, h: 0.7, rectRadius: 0.14, fill: { color: g.c } });
  s.addText(g.phase.toUpperCase(), { x, y: gY, w: gW, h: 0.7, fontSize: 13, bold: true, color: COLOR.bg, align: "center", valign: "middle", charSpacing: 1, fontFace: FONT });
  s.addText(g.t, { x: x + 0.25, y: gY + 0.9, w: gW - 0.5, h: 0.5, fontSize: 18, bold: true, color: COLOR.ink, fontFace: FONT });
  s.addText(g.d, { x: x + 0.25, y: gY + 1.45, w: gW - 0.5, h: 1.25, fontSize: 13.5, color: COLOR.body, fontFace: FONT, lineSpacingMultiple: 1.25, valign: "top" });
  s.addText([{ text: "Focus metric: ", options: { color: COLOR.faint } }, { text: g.metric, options: { bold: true, color: COLOR.tealDk } }], { x: x + 0.25, y: gY + 2.75, w: gW - 0.5, h: 0.4, fontSize: 12.5, fontFace: FONT });
});

// ===========================================================================
// SLIDE 10 — TEAM (member cards with drawn avatar circles + initials)
// Avatars are colored ellipses with initials — no photos / image assets.
// ===========================================================================
s = pptx.addSlide({ masterName: MASTER });
addHeader(s, "The people building it", "Team");
const team = [
  { name: "Ada Okafor", role: "CEO & Co-founder", bio: "Ex-Stripe infra. Scaled deploy systems for 10k+ services.", c: COLOR.teal },
  { name: "Ravi Menon", role: "CTO & Co-founder", bio: "Ex-HashiCorp. Built the scheduler behind a major PaaS.", c: COLOR.coral },
  { name: "Lena Brandt", role: "Head of Product", bio: "Ex-Vercel. Led the developer-experience surface end to end.", c: COLOR.gold },
  { name: "Tomás Ruiz", role: "Head of GTM", bio: "Ex-Datadog. Scaled PLG-to-enterprise from $2M to $80M ARR.", c: COLOR.tealDk },
];
const tcW = (CONTENT_W - 0.5 * (team.length - 1)) / team.length;
team.forEach((m, i) => {
  const x = PAGE.margin + i * (tcW + 0.5);
  const y = 2.0;
  s.addShape(pptx.ShapeType.roundRect, { x, y, w: tcW, h: 4.3, rectRadius: 0.14, fill: { color: COLOR.panel }, line: { color: COLOR.line, width: 1 } });
  // drawn avatar: colored circle + white initials
  const av = 1.3;
  const avX = x + (tcW - av) / 2;
  s.addShape(pptx.ShapeType.ellipse, { x: avX, y: y + 0.4, w: av, h: av, fill: { color: m.c } });
  const initials = m.name.split(" ").map((p) => p.charAt(0)).join("");
  s.addText(initials, { x: avX, y: y + 0.4, w: av, h: av, fontSize: 34, bold: true, color: COLOR.white, align: "center", valign: "middle", fontFace: FONT });
  s.addText(m.name, { x: x + 0.15, y: y + 1.95, w: tcW - 0.3, h: 0.45, fontSize: 16, bold: true, color: COLOR.ink, align: "center", fontFace: FONT });
  s.addText(m.role, { x: x + 0.15, y: y + 2.4, w: tcW - 0.3, h: 0.4, fontSize: 12.5, bold: true, color: COLOR.teal, align: "center", fontFace: FONT });
  s.addText(m.bio, { x: x + 0.2, y: y + 2.9, w: tcW - 0.4, h: 1.25, fontSize: 12, color: COLOR.body, align: "center", fontFace: FONT, lineSpacingMultiple: 1.25, valign: "top" });
});

// ===========================================================================
// SLIDE 11 — THE ASK (funding amount + use-of-funds as a drawn stacked bar)
// Dark "moment" slide. A single horizontal bar split into colored segments
// shows the allocation; a legend lists each slice. No chart, no image.
// ===========================================================================
s = pptx.addSlide();
s.background = { color: COLOR.bg };
s.addText("THE ASK", { x: PAGE.margin, y: 0.7, w: CONTENT_W, h: 0.4, fontSize: 13, bold: true, color: COLOR.teal, charSpacing: 3, fontFace: FONT });
s.addText(
  [
    { text: "Raising ", options: { color: COLOR.white } },
    { text: "$6M", options: { bold: true, color: COLOR.teal } },
    { text: " seed", options: { color: COLOR.white } },
  ],
  { x: PAGE.margin, y: 1.15, w: CONTENT_W, h: 1.0, fontSize: 46, bold: true, fontFace: FONT, valign: "middle" },
);
s.addText("18 months of runway to reach $3M ARR and a Series A profile.", { x: PAGE.margin, y: 2.25, w: CONTENT_W, h: 0.5, fontSize: 18, color: COLOR.mist, fontFace: FONT });
// use-of-funds stacked horizontal bar
const useFunds = [
  { l: "Engineering", pct: 45, c: COLOR.teal },
  { l: "Go-to-market", pct: 30, c: COLOR.gold },
  { l: "Infrastructure", pct: 15, c: COLOR.tealDk },
  { l: "G&A", pct: 10, c: COLOR.coral },
];
const fundsBarX = PAGE.margin;
const fundsBarY = 3.55;
const fundsBarW = CONTENT_W;
const fundsBarH = 0.85;
let cursor = fundsBarX;
useFunds.forEach((u, i) => {
  const w = (u.pct / 100) * fundsBarW;
  // rounded ends only on first/last segment for a clean pill look
  const isFirst = i === 0;
  const isLast = i === useFunds.length - 1;
  const shape = isFirst || isLast ? pptx.ShapeType.roundRect : pptx.ShapeType.rect;
  s.addShape(shape, { x: cursor, y: fundsBarY, w, h: fundsBarH, rectRadius: 0.12, fill: { color: u.c } });
  // percent label centered in segment
  s.addText(`${u.pct}%`, { x: cursor, y: fundsBarY, w, h: fundsBarH, fontSize: 16, bold: true, color: u.c === COLOR.gold ? COLOR.bg : COLOR.white, align: "center", valign: "middle", fontFace: FONT });
  cursor += w;
});
// legend row beneath the bar
let legCursor = fundsBarX;
useFunds.forEach((u) => {
  const w = (u.pct / 100) * fundsBarW;
  s.addShape(pptx.ShapeType.rect, { x: legCursor, y: fundsBarY + fundsBarH + 0.35, w: 0.28, h: 0.28, fill: { color: u.c } });
  s.addText(u.l, { x: legCursor + 0.4, y: fundsBarY + fundsBarH + 0.3, w: w + 1.2, h: 0.4, fontSize: 14, color: COLOR.white, valign: "middle", fontFace: FONT });
  legCursor += w;
});
// milestone chips beneath the legend
const milestones = ["$3M ARR", "3,000 paying teams", "Enterprise tier GA", "SOC 2 Type II"];
milestones.forEach((m, i) => {
  const chipW = 2.85;
  const x = PAGE.margin + i * (chipW + 0.21);
  const y = 5.7;
  s.addShape(pptx.ShapeType.roundRect, { x, y, w: chipW, h: 0.7, rectRadius: 0.14, fill: { color: COLOR.bgAlt }, line: { color: COLOR.tealDk, width: 1 } });
  s.addText(m, { x, y, w: chipW, h: 0.7, fontSize: 14, bold: true, color: COLOR.white, align: "center", valign: "middle", fontFace: FONT });
});
s.addText("18-month milestones", { x: PAGE.margin, y: 5.35, w: CONTENT_W, h: 0.3, fontSize: 12, italic: true, color: COLOR.faint, fontFace: FONT });

// ===========================================================================
// SLIDE 12 — CLOSING / CONTACT (full-bleed dark, mirrors the cover)
// ===========================================================================
s = pptx.addSlide();
s.background = { color: COLOR.bg };
// mirrored accent rings, bottom-left
s.addShape(pptx.ShapeType.ellipse, { x: -1.7, y: 4.0, w: 5.0, h: 5.0, fill: { type: "none" }, line: { color: COLOR.tealDk, width: 1.25 } });
s.addShape(pptx.ShapeType.ellipse, { x: -0.8, y: 4.9, w: 3.2, h: 3.2, fill: { type: "none" }, line: { color: COLOR.coral, width: 1.25 } });
s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: PAGE.w, h: 0.18, fill: { color: COLOR.teal } });
addLogoMark(s, 0.85, 0.85, 0.62);
s.addText(BRAND.name, { x: 1.6, y: 0.85, w: 6, h: 0.62, fontSize: 24, bold: true, color: COLOR.white, valign: "middle", fontFace: FONT });
s.addText("Let's build the deploy\nlayer for every team.", {
  x: 0.82, y: 2.6, w: 11, h: 1.9, fontSize: 46, bold: true, color: COLOR.white, fontFace: FONT, lineSpacingMultiple: 1.02,
});
s.addText(
  [
    { text: "ada@nimbus.example", options: { bold: true, color: COLOR.teal } },
    { text: "      nimbus.example      @nimbushq", options: { color: COLOR.mist } },
  ],
  { x: 0.85, y: 4.75, w: 11.5, h: 0.5, fontSize: 18, fontFace: FONT },
);
s.addText("Thanks for reading. Let's talk.", { x: 0.85, y: 5.5, w: 11, h: 0.5, fontSize: 15, color: COLOR.faint, fontFace: FONT });

// ---------------------------------------------------------------------------
// WRITE — the only side effect. Path comes from argv[2] (build.sh passes it).
// ---------------------------------------------------------------------------
const out = process.argv[2] || "out.pptx";
await pptx.writeFile({ fileName: out });
