"use client";

import { useEffect, useRef } from "react";

const WORD = "GAIA";
const DOT_RGB = "228,228,231";
const COVERAGE_FLOOR = 0.08;
const MIN_DOT_RADIUS = 0.45;

interface WordRaster {
  alpha: Uint8ClampedArray;
  width: number;
  height: number;
  glyphH: number;
}

function smoothstep(a: number, b: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
}

/** Rasterize the wordmark offscreen and return its alpha channel + metrics. */
function rasterizeWord(family: string, cssW: number): WordRaster | null {
  const off = document.createElement("canvas");
  const ctx = off.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;

  ctx.font = `700 100px ${family}`;
  const fontPx = (100 * cssW) / ctx.measureText(WORD).width;
  ctx.font = `700 ${fontPx}px ${family}`;
  const metrics = ctx.measureText(WORD);
  const ascent = metrics.actualBoundingBoxAscent;
  const glyphH = ascent + metrics.actualBoundingBoxDescent;

  off.width = Math.ceil(cssW);
  off.height = Math.ceil(glyphH);
  ctx.font = `700 ${fontPx}px ${family}`;
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#fff";
  ctx.fillText(WORD, (cssW - metrics.width) / 2, ascent);

  return {
    alpha: ctx.getImageData(0, 0, off.width, off.height).data,
    width: off.width,
    height: off.height,
    glyphH,
  };
}

/** 3x3 area coverage for one grid cell, so radii ramp smoothly on glyph edges. */
function cellCoverage(
  raster: WordRaster,
  col: number,
  row: number,
  cell: number,
): number {
  let acc = 0;
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
      acc += raster.alpha[(py * raster.width + px) * 4 + 3];
    }
  }
  return acc / (9 * 255);
}

/** Area-true halftone: sqrt-coverage dots with a size + tone fade to black. */
function drawHalftone(
  ctx: CanvasRenderingContext2D,
  raster: WordRaster,
  cssW: number,
  cssH: number,
  cell: number,
): void {
  const maxR = cell * 0.46;
  const cols = Math.floor(cssW / cell);
  const rows = Math.floor(raster.glyphH / cell);

  ctx.clearRect(0, 0, cssW, cssH);
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const coverage = cellCoverage(raster, col, row, cell);
      if (coverage <= COVERAGE_FLOOR) continue;

      const x = (col + 0.5) * cell;
      const y = (row + 0.5) * cell;
      const t = Math.min(1, y / cssH);
      const radius = maxR * Math.sqrt(coverage) * (1 - 0.62 * t);
      if (radius < MIN_DOT_RADIUS) continue;

      const alpha = 1 - 0.88 * smoothstep(0.1, 1.05, t);
      ctx.fillStyle = `rgba(${DOT_RGB},${alpha.toFixed(3)})`;
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

/**
 * Halftone footer wordmark: the display font's letterforms rasterized offscreen
 * and re-drawn as a dot grid whose size and brightness fade toward the bottom.
 * Purely decorative, static, DPR-crisp.
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
      await document.fonts.load(`700 100px ${family}`);
      if (cancelled) return;

      const cssW = canvas.clientWidth;
      if (!cssW) return;
      const raster = rasterizeWord(family, cssW);
      if (!raster) return;

      const cssH = raster.glyphH;
      const cell = Math.max(11, Math.min(17, cssW / 78));
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
        style={{ aspectRatio: "14 / 3" }}
      />
    </>
  );
}
