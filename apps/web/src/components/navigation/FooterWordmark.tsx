"use client";

import { useEffect, useRef } from "react";

const WORD = "GAIA";
/** Colored circle mark, drawn at the same height as the lettering. */
const LOGO_SRC = "/images/logos/logo.webp";
/** Gap between the mark and the lettering, as a fraction of the row height. */
const GAP_RATIO = 0.22;
const TEXT_RGB = "#e4e4e7";
const COVERAGE_FLOOR = 0.08;
const MIN_DOT_RADIUS = 0.45;

interface WordRaster {
  pixels: Uint8ClampedArray;
  width: number;
  height: number;
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
function drawHalftone(
  ctx: CanvasRenderingContext2D,
  raster: WordRaster,
  cssW: number,
  cssH: number,
  cell: number,
): void {
  const maxR = cell * 0.44;
  const cols = Math.floor(cssW / cell);
  const rows = Math.floor(raster.height / cell);

  ctx.clearRect(0, 0, cssW, cssH);
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
      const radius =
        maxR *
        Math.sqrt(coverage) *
        toneMul *
        (1 - 0.7 * smoothstep(0.2, 1.05, t));
      if (radius < MIN_DOT_RADIUS) continue;

      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

/**
 * Halftone footer lockup: the colored circle mark and the display-font
 * lettering composed at equal height, rasterized offscreen and redrawn as a
 * color-sampled dot grid that fades toward the bottom. Decorative, static,
 * DPR-crisp.
 */
export function FooterWordmark() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const probeRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const probe = probeRef.current;
    if (!canvas || !probe) return;

    let cancelled = false;

    const build = async () => {
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
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      drawHalftone(ctx, raster, cssW, cssH, cell);
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
      clearTimeout(timer);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return (
    <>
      {/* Invisible probe that resolves the hashed display-font family for canvas. */}
      <span
        ref={probeRef}
        aria-hidden
        className="absolute h-0 w-0 overflow-hidden font-serif font-bold"
      />
      {/* Reserved aspect ratio prevents layout shift before the first draw. */}
      <canvas
        ref={canvasRef}
        aria-hidden
        className="block w-full"
        style={{ aspectRatio: "23 / 4" }}
      />
    </>
  );
}
