"use client";

import { useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";

const WORD = "GAIA";
/** Colored circle mark, drawn at the same height as the lettering. */
const LOGO_SRC = "/images/logos/logo.webp";
/** Gap between the mark and the lettering, as a fraction of the row height. */
const GAP_RATIO = 0.22;
const TEXT_RGB = "#e4e4e7";
const COVERAGE_FLOOR = 0.08;
const MIN_DOT_RADIUS = 0.45;

// Pointer-interaction tuning.
/** Extra swell at the pointer, fading to zero over RIPPLE_RADIUS. */
const RIPPLE_LIFT = 0.45;
const RIPPLE_RADIUS = 120;

// Click-ripple tuning.
/** Peak swell of the click wave at its origin. */
const CLICK_AMP = 0.55;
/** Wavefront speed across the wordmark, css px per second. */
const CLICK_SPEED = 900;
/** Seconds for one dot to complete its swell bump as the front passes. */
const CLICK_RISE = 0.32;
/** Fraction of the amplitude lost at the far edge of the canvas. */
const CLICK_EDGE_FALLOFF = 0.45;
/** Opacity of the un-blended white layer at the peak of the click wave. */
const CLICK_GLOW_ALPHA = 0.9;
/** Below this the white layer is invisible — skip the fill entirely. */
const GLOW_EPSILON = 0.02;

interface WordRaster {
  pixels: Uint8ClampedArray;
  width: number;
  height: number;
}

interface Dot {
  x: number;
  y: number;
  base: number;
  radius: number;
  /** 0..1 share of the click wave at this dot, drives the white layer. */
  glow: number;
}

/** A click-ripple wavefront expanding from a pointerdown point. */
interface ClickWave {
  x: number;
  y: number;
  /** performance.now() at pointerdown. */
  start: number;
}

function smoothstep(a: number, b: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

/**
 * Compose the lockup — circle logo and the word at the SAME height, side by
 * side — sized so the whole row spans cssW, then return its pixel data.
 */
function rasterizeLockup(
  family: string,
  logo: HTMLImageElement,
  cssW: number,
): WordRaster | null {
  const off = document.createElement("canvas");
  const ctx = off.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;

  // Measure at 100px to solve the font size where logo + gap + text == cssW
  // with the logo height locked to the glyph height.
  ctx.font = `700 100px ${family}`;
  const m100 = ctx.measureText(WORD);
  const h100 = m100.actualBoundingBoxAscent + m100.actualBoundingBoxDescent;
  const w100 = m100.width;
  const logoAspect = logo.naturalWidth / logo.naturalHeight;
  const fontPx = (100 * cssW) / (h100 * (logoAspect + GAP_RATIO) + w100);

  ctx.font = `700 ${fontPx}px ${family}`;
  const m = ctx.measureText(WORD);
  const ascent = m.actualBoundingBoxAscent;
  const rowH = ascent + m.actualBoundingBoxDescent;
  const logoW = rowH * logoAspect;

  off.width = Math.ceil(cssW);
  off.height = Math.ceil(rowH);
  ctx.font = `700 ${fontPx}px ${family}`;
  ctx.textBaseline = "alphabetic";
  ctx.drawImage(logo, 0, 0, logoW, rowH);
  ctx.fillStyle = TEXT_RGB;
  ctx.fillText(WORD, logoW + rowH * GAP_RATIO, ascent);

  return {
    pixels: ctx.getImageData(0, 0, off.width, off.height).data,
    width: off.width,
    height: off.height,
  };
}

interface CellSample {
  coverage: number;
  r: number;
  g: number;
  b: number;
}

/** 3x3 area sample for one grid cell: alpha coverage plus the alpha-weighted
 * average color, so the logo's own shading carries through into the dots. */
function sampleCell(
  raster: WordRaster,
  col: number,
  row: number,
  cell: number,
): CellSample {
  let aAcc = 0;
  let rAcc = 0;
  let gAcc = 0;
  let bAcc = 0;
  for (let sy = 0; sy < 3; sy++) {
    for (let sx = 0; sx < 3; sx++) {
      const px = Math.min(
        raster.width - 1,
        Math.floor(col * cell + ((sx + 0.5) * cell) / 3),
      );
      const py = Math.min(
        raster.height - 1,
        Math.floor(row * cell + ((sy + 0.5) * cell) / 3),
      );
      const i = (py * raster.width + px) * 4;
      const a = raster.pixels[i + 3];
      aAcc += a;
      rAcc += raster.pixels[i] * a;
      gAcc += raster.pixels[i + 1] * a;
      bAcc += raster.pixels[i + 2] * a;
    }
  }
  const coverage = aAcc / (9 * 255);
  return {
    coverage,
    r: aAcc > 0 ? Math.round(rAcc / aAcc) : 0,
    g: aAcc > 0 ? Math.round(gAcc / aAcc) : 0,
    b: aAcc > 0 ? Math.round(bAcc / aAcc) : 0,
  };
}

/** Area-true halftone: uniform grid, FULLY OPAQUE white dots. Tone is carried
 * by dot size alone. The logo's three flat blues have a narrow luminance
 * spread, so we contrast-stretch it before mapping to size — otherwise the
 * shades come out within ~15% of each other and the detail is invisible. */
function buildDots(
  raster: WordRaster,
  cssW: number,
  cssH: number,
  cell: number,
): Dot[] {
  const maxR = cell * 0.44;
  const cols = Math.floor(cssW / cell);
  const rows = Math.floor(raster.height / cell);
  const dots: Dot[] = [];

  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const { coverage, r, g, b } = sampleCell(raster, col, row, cell);
      if (coverage <= COVERAGE_FLOOR) continue;

      const x = (col + 0.5) * cell;
      const y = (row + 0.5) * cell;
      const t = Math.min(1, y / cssH);

      // The logo has three flat blues plus white text. Contrast-stretch the
      // narrow luminance spread, then POSTERIZE into three discrete shade
      // bands so each blue reads as a distinctly different dot size (dark
      // navy → tiny, mid blue → medium, light cyan / white → full).
      const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
      const stretched = Math.min(1, Math.max(0, (lum - 0.1) / 0.55));
      const toneMul = stretched < 0.38 ? 0.28 : stretched < 0.72 ? 0.62 : 1.0;
      const base =
        maxR *
        Math.sqrt(coverage) *
        toneMul *
        (1 - 0.7 * smoothstep(0.2, 1.05, t));
      if (base < MIN_DOT_RADIUS) continue;

      dots.push({ x, y, base, radius: base, glow: 0 });
    }
  }
  return dots;
}

/** Draw every dot as one batched path. Radius is read from each dot's current
 * state, so the same call serves both the static draw and the animated loop. */
function drawDots(ctx: CanvasRenderingContext2D, dots: Dot[]): void {
  ctx.fillStyle = "rgba(255,255,255,0.82)";
  ctx.beginPath();
  for (const dot of dots) {
    ctx.moveTo(dot.x + dot.radius, dot.y);
    ctx.arc(dot.x, dot.y, dot.radius, 0, Math.PI * 2);
  }
  ctx.fill();
}

/**
 * Draw the white layer that rides the click wave. It lives on its own canvas
 * with NO blend mode, so where the wave peaks the dots read as plain white
 * instead of the overlay-blended base — the blend appears to change as the
 * ripple passes. Dots are bucketed by opacity so the whole layer still draws
 * in a handful of batched paths rather than one fill per dot.
 */
function drawGlow(ctx: CanvasRenderingContext2D, dots: Dot[]): void {
  const buckets = new Map<number, Dot[]>();
  for (const dot of dots) {
    if (dot.glow < GLOW_EPSILON) continue;
    const step = Math.round(dot.glow * 10);
    const bucket = buckets.get(step);
    if (bucket) bucket.push(dot);
    else buckets.set(step, [dot]);
  }

  for (const [step, bucketDots] of buckets) {
    ctx.fillStyle = `rgba(255,255,255,${(step / 10) * CLICK_GLOW_ALPHA})`;
    ctx.beginPath();
    for (const dot of bucketDots) {
      ctx.moveTo(dot.x + dot.radius, dot.y);
      ctx.arc(dot.x, dot.y, dot.radius, 0, Math.PI * 2);
    }
    ctx.fill();
  }
}

/**
 * Pointer interaction: dots inside a small circle around the cursor swell
 * and track it 1:1 as it moves over the wordmark, and a pointerdown sends a
 * wavefront rippling across the whole lockup. Dot sizes
 * are computed straight from the cursor position every frame — no springs,
 * no lag — smoothness comes from the falloff shape and the cursor's own
 * continuous motion. The rAF loop only runs while a click wave is alive;
 * returns a cleanup that detaches listeners and cancels the loop.
 */
function attachPointerInteraction(
  canvas: HTMLCanvasElement,
  ctx: CanvasRenderingContext2D,
  glowCtx: CanvasRenderingContext2D,
  dots: Dot[],
  cssW: number,
  cssH: number,
): () => void {
  let pointerInside = false;
  let pointerX = 0;
  let pointerY = 0;
  const waves: ClickWave[] = [];
  let raf = 0;

  const toCanvasPoint = (e: PointerEvent): { x: number; y: number } => {
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };

  const frame = (now: number): void => {
    // Prune click waves whose front has crossed the whole canvas (all times
    // in ms).
    const waveLifetime = (cssW / CLICK_SPEED + CLICK_RISE + 0.25) * 1000;
    for (let i = waves.length - 1; i >= 0; i--) {
      if (now - waves[i].start > waveLifetime) waves.splice(i, 1);
    }

    for (const dot of dots) {
      // Ripple center is the cursor itself — synced 1:1, no delay.
      const dist = Math.hypot(dot.x - pointerX, dot.y - pointerY);
      // Only dots inside the cursor's falloff circle are affected — the
      // rest of the wordmark stays at rest.
      const ripple = RIPPLE_LIFT * smoothstep(RIPPLE_RADIUS, 0, dist);
      let target = pointerInside ? ripple : 0;

      // Sum every active click wave: each dot swells on a sin bump as the
      // wavefront reaches it (arrival time = distance / CLICK_SPEED), so the
      // ripple physically travels across the whole lockup.
      let click = 0;
      for (const wave of waves) {
        const d = Math.hypot(dot.x - wave.x, dot.y - wave.y);
        const phase =
          ((now - wave.start) / 1000 - d / CLICK_SPEED) / CLICK_RISE;
        if (phase < 0 || phase > 1) continue;
        const edgeFalloff = 1 - CLICK_EDGE_FALLOFF * smoothstep(0, cssW, d);
        click += CLICK_AMP * edgeFalloff * Math.sin(Math.PI * phase);
      }
      target += click;

      dot.radius = dot.base * (1 + target);
      // The white layer tracks the click wave only — hovering swells the
      // dots but must not repaint them, so the two reads stay distinct.
      dot.glow = Math.min(1, click / CLICK_AMP);
    }

    ctx.clearRect(0, 0, cssW, cssH);
    drawDots(ctx, dots);
    glowCtx.clearRect(0, 0, cssW, cssH);
    drawGlow(glowCtx, dots);

    raf = waves.length > 0 ? requestAnimationFrame(frame) : 0;
  };

  const start = (): void => {
    if (raf) return;
    raf = requestAnimationFrame(frame);
  };

  const onEnter = (e: PointerEvent): void => {
    const p = toCanvasPoint(e);
    pointerInside = true;
    pointerX = p.x;
    pointerY = p.y;
    start();
  };

  const onMove = (e: PointerEvent): void => {
    const p = toCanvasPoint(e);
    pointerX = p.x;
    pointerY = p.y;
    // A pointermove on the canvas implies the pointer is over it — adopt it
    // unconditionally. Without this, a rebuild (resize) while hovering, or a
    // pointer already inside when the interaction attached, would leave the
    // swell dead until a leave/re-enter cycle.
    pointerInside = true;
    start();
  };

  const onDown = (e: PointerEvent): void => {
    const p = toCanvasPoint(e);
    waves.push({ x: p.x, y: p.y, start: performance.now() });
    start();
  };

  const onLeave = (): void => {
    pointerInside = false;
    // Draw one final frame at rest (the loop stops on its own once no
    // click wave is alive).
    start();
  };

  canvas.addEventListener("pointerenter", onEnter);
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerdown", onDown);
  canvas.addEventListener("pointerleave", onLeave);
  canvas.addEventListener("pointercancel", onLeave);

  // If the pointer is already over the canvas when the interaction attaches
  // (e.g. the page scrolled or resized under a stationary pointer), adopt it
  // so the swell isn't dead until the pointer moves. The exact position is
  // unknown — the first pointermove corrects the ripple center.
  if (canvas.matches(":hover")) {
    pointerInside = true;
    pointerX = cssW / 2;
    pointerY = cssH / 2;
    start();
  }

  return () => {
    canvas.removeEventListener("pointerenter", onEnter);
    canvas.removeEventListener("pointermove", onMove);
    canvas.removeEventListener("pointerdown", onDown);
    canvas.removeEventListener("pointerleave", onLeave);
    canvas.removeEventListener("pointercancel", onLeave);
    if (raf) cancelAnimationFrame(raf);
  };
}

/**
 * Halftone footer lockup: the colored circle mark and the display-font
 * lettering composed at equal height, rasterized offscreen and redrawn as a
 * color-sampled dot grid that fades toward the bottom. Decorative, DPR-crisp.
 * While the pointer is over the wordmark, dots inside a small circle around
 * the cursor swell and track it 1:1, and a click ripples across every dot
 * (skipped under reduced motion — static draw only).
 */
export function FooterWordmark() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const glowRef = useRef<HTMLCanvasElement>(null);
  const probeRef = useRef<HTMLSpanElement>(null);
  const shouldReduceMotion = useReducedMotion();

  useEffect(() => {
    const canvas = canvasRef.current;
    const glowCanvas = glowRef.current;
    const probe = probeRef.current;
    if (!canvas || !glowCanvas || !probe) return;

    let cancelled = false;
    let detachInteraction: (() => void) | null = null;

    const build = async () => {
      detachInteraction?.();
      detachInteraction = null;

      // next/font hashes the family name — resolve it from a probe element.
      const family = getComputedStyle(probe).fontFamily;
      const [logo] = await Promise.all([
        loadImage(LOGO_SRC),
        document.fonts.load(`700 100px ${family}`),
      ]);
      if (cancelled) return;

      const cssW = canvas.clientWidth;
      if (!cssW) return;
      const raster = rasterizeLockup(family, logo, cssW);
      if (!raster) return;

      const cssH = raster.height;
      const cell = Math.max(6, Math.min(9, cssW / 165));
      const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      canvas.style.height = `${cssH}px`;
      glowCanvas.width = canvas.width;
      glowCanvas.height = canvas.height;
      const ctx = canvas.getContext("2d");
      const glowCtx = glowCanvas.getContext("2d");
      if (!ctx || !glowCtx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      glowCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const dots = buildDots(raster, cssW, cssH, cell);
      drawDots(ctx, dots);
      glowCtx.clearRect(0, 0, cssW, cssH);
      if (shouldReduceMotion) return;

      detachInteraction = attachPointerInteraction(
        canvas,
        ctx,
        glowCtx,
        dots,
        cssW,
        cssH,
      );
    };

    build();

    let timer: ReturnType<typeof setTimeout>;
    const onResize = () => {
      clearTimeout(timer);
      timer = setTimeout(build, 180);
    };
    window.addEventListener("resize", onResize);
    return () => {
      cancelled = true;
      detachInteraction?.();
      clearTimeout(timer);
      window.removeEventListener("resize", onResize);
    };
  }, [shouldReduceMotion]);

  return (
    <>
      {/* Invisible probe that resolves the hashed display-font family for canvas. */}
      <span
        ref={probeRef}
        aria-hidden
        className="absolute h-0 w-0 overflow-hidden font-serif font-bold"
      />
      {/* Two stacked layers, because a canvas can only carry one blend mode:
          the base halftone blends with the wallpaper, and the click ripple
          fades in an un-blended white copy of the same dots on top, so the
          wave reads as white as it travels. `relative` (no z-index) keeps
          both blending against the footer wallpaper — a stacking context here
          would isolate them and kill the blend entirely. */}
      <div className="relative">
        {/* Reserved aspect ratio prevents layout shift before the first draw. */}
        <canvas
          ref={canvasRef}
          aria-hidden
          className="block w-full mix-blend-overlay"
          style={{ aspectRatio: "23 / 4" }}
        />
        <canvas
          ref={glowRef}
          aria-hidden
          className="pointer-events-none absolute inset-0 block h-full w-full"
        />
      </div>
    </>
  );
}
