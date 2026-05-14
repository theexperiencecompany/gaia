"use client";

import { useEffect, useRef } from "react";
import { SPECTRUM_BINS } from "./useVoiceSpectrum";

export type VoiceMode = "user" | "gaia";

interface VoiceGradientProps {
  mode: VoiceMode;
  spectrum: Float32Array;
}

/* ─── Vertex shader: full-screen quad with UVs in [0..1] ────────────────── */
const VERT = /* glsl */ `#version 300 es
in vec2 aPos;
out vec2 vUv;
void main() {
  vUv = aPos * 0.5 + 0.5;
  gl_Position = vec4(aPos, 0.0, 1.0);
}
`;

/* ─── Fragment shader: uniform body + soft volumetric peak ──────────────────
 *
 * Architectural intent: there is exactly ONE wave envelope. The area below
 * the envelope is filled with a SINGLE vertical gradient (dark navy at the
 * envelope → bright light blue at the very bottom). The area above the
 * envelope diffuses softly into black. No stacked layers, no per-layer
 * gradients, no ridge strokes — those were the source of the light-dark-
 * light banding. A chromatic tint lives right AT the envelope, producing
 * the cyan/green dispersion visible at peak tops in the reference. Heavy
 * smoothstep ranges fake a wide gaussian blur on the wave silhouette.
 */
const FRAG = /* glsl */ `#version 300 es
precision highp float;

in vec2 vUv;
out vec4 fragColor;

uniform float uSpectrum[${SPECTRUM_BINS}];
uniform float uTime;
uniform vec2  uResolution;
/** 0 → user palette (white/silver), 1 → GAIA palette (cyan/blue). Smoothly lerped. */
uniform float uMode;

/* ─── Hash / value-noise / fBM (used to perturb the envelope organically) ── */
float hash21(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}
float vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 4; i++) {
    v += a * vnoise(p);
    p *= 2.02;
    a *= 0.5;
  }
  return v;
}

/* ─── Catmull-Rom interpolation of the 24-bin spectrum array ────────────── */
float specAt(float fi) {
  fi = clamp(fi, 0.0, float(${SPECTRUM_BINS} - 1));
  float f = floor(fi);
  float t = fi - f;
  int i1 = int(f);
  int i0 = max(i1 - 1, 0);
  int i2 = min(i1 + 1, ${SPECTRUM_BINS} - 1);
  int i3 = min(i1 + 2, ${SPECTRUM_BINS} - 1);
  float p0 = uSpectrum[i0];
  float p1 = uSpectrum[i1];
  float p2 = uSpectrum[i2];
  float p3 = uSpectrum[i3];
  float t2 = t * t;
  float t3 = t2 * t;
  return 0.5 * (
    (2.0 * p1) +
    (-p0 + p2) * t +
    (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2 +
    (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
  );
}

/* ─── ACES-ish tone map so highlights don't blow out ────────────────────── */
vec3 tonemap(vec3 c) {
  const float a = 2.51, b = 0.03, k = 2.43, d = 0.59, e = 0.14;
  return clamp((c * (a * c + b)) / (c * (k * c + d) + e), 0.0, 1.0);
}

/** Spectrum-driven wave height in [0..1]. binShift lets ghost layers sample
    a phase-shifted slice of the spectrum so each ghost has its own shape. */
float waveHeight(float xNorm, float binShift) {
  float fi = xNorm * float(${SPECTRUM_BINS} - 1) + binShift;
  float v = pow(max(0.0, specAt(fi)), 1.8);
  float jitter = (fbm(vec2(xNorm * 4.5 + binShift, uTime * 0.00012)) - 0.5) * 0.05;
  return clamp(v + jitter, 0.0, 1.0);
}

void main() {
  vec2 uv = vUv;
  // Flip y so top of canvas = 0, bottom = 1 (matches our mental model).
  uv.y = 1.0 - uv.y;
  float aspect = uResolution.x / uResolution.y;

  /* ─── Palette ───────────────────────────────────────────────────────── */
  /* User mode (cool slate / white), GAIA mode (deep navy / muted blue). */
  vec3 bandBottomU = vec3(0.78, 0.85, 0.96);
  vec3 bandTopU    = vec3(0.32, 0.42, 0.62);
  vec3 navyU       = vec3(0.05, 0.08, 0.16);
  vec3 tipU        = vec3(0.95, 0.98, 1.00);

  vec3 bandBottomG = vec3(0.20, 0.50, 0.78);
  vec3 bandTopG    = vec3(0.02, 0.10, 0.26);   // dark — bleeds into navy/black above
  vec3 navyG       = vec3(0.02, 0.09, 0.22);
  vec3 tipG        = vec3(0.45, 0.95, 0.80);   // cyan-green chromatic dispersion

  vec3 bandBottom = mix(bandBottomU, bandBottomG, uMode);
  vec3 bandTop    = mix(bandTopU,    bandTopG,    uMode);
  vec3 navy       = mix(navyU,       navyG,       uMode);
  vec3 tip        = mix(tipU,        tipG,        uMode);

  /* ─── BG — bleeds from pure black at top to deep navy at bottom so the
       wave's top fade doesn't snap against pure black ─────────────────── */
  vec3 color = mix(vec3(0.0), navy * 0.55, pow(uv.y, 1.8));

  /* ─── Heavy volumetric fBM (sampled at two scales) used by every layer
       to break up the body. WAY stronger than before — this is what makes
       the wave look like clouds emitting light, not a flat fill. ─────── */
  vec2 c1 = vec2(uv.x * aspect * 2.0, uv.y * 2.0) +
            vec2(uTime * 0.00006, uTime * 0.00003);
  vec2 c2 = vec2(uv.x * aspect * 5.5, uv.y * 5.5) +
            vec2(uTime * -0.00009, uTime * 0.00005);
  float bigCloud = fbm(c1);
  float fineCloud = fbm(c2);
  float density = bigCloud * 0.7 + fineCloud * 0.3;

  /* ─── Three additive ghost waves at different depths ───────────────── */
  /* Each "layer" is just a wave silhouette + body fill, composited as
     LIGHT (additive). The cumulative brightness across overlapping layers
     creates real luminous depth, not a graphic stack. */

  /* Far back ghost — very wide feather, low alpha, dark blue */
  {
    float h = waveHeight(uv.x, 4.0);
    float yBase = 0.68 - h * 0.30;
    float dist = uv.y - yBase;
    float mask = 0.5 + 0.5 * tanh(dist / 0.20 * 1.6);
    vec3 col = mix(bandTop * 0.5, bandTop, smoothstep(0.0, 0.6, dist));
    col *= 0.5 + density * 1.1;
    color += col * mask * 0.45;
  }

  /* Mid ghost */
  {
    float h = waveHeight(uv.x, 1.8);
    float yBase = 0.76 - h * 0.30;
    float dist = uv.y - yBase;
    float mask = 0.5 + 0.5 * tanh(dist / 0.14 * 1.7);
    vec3 col = mix(bandTop, mix(bandTop, bandBottom, 0.55), smoothstep(0.0, 0.4, dist));
    col *= 0.5 + density * 1.2;
    color += col * mask * 0.6;
  }

  /* Foreground — sharper, brightest body */
  float hMain = waveHeight(uv.x, 0.0);
  float envY = 0.85 - hMain * 0.30;
  float distMain = uv.y - envY;
  {
    float mask = 0.5 + 0.5 * tanh(distMain / 0.09 * 1.8);
    float bodyT = clamp(distMain / max(0.0001, 1.0 - envY), 0.0, 1.0);
    vec3 col = mix(bandTop * 1.2, bandBottom, smoothstep(0.0, 0.7, bodyT));
    /* HEAVY density modulation — body is half-strength baseline plus fBM
       boost. This is what produces visible cloud-like volumetric texture. */
    col *= 0.45 + density * 1.3;
    color += col * mask * 0.85;
  }

  /* ─── Radial peak glow — bright cyan halo radiating outward from the
       highest point of the main wave at this x. Creates the "lit emission"
       feel. Strength scales with local wave height. ─────────────────── */
  {
    float dist = abs(distMain);
    float glow = exp(-pow(dist / 0.18, 1.4));
    float strength = pow(hMain, 1.2);
    vec3 glowColor = mix(bandBottom * 1.2, tip, smoothstep(0.4, 1.0, hMain));
    color += glowColor * glow * strength * 0.55;
  }

  /* ─── Chromatic peak tip — narrow cyan-green band right AT the envelope.
       Only fires on tall peaks so the colour dispersion reads as "lit
       lens" at the summit rather than smearing across the whole band. */
  if (hMain > 0.25) {
    float tipBand = exp(-pow(distMain * 30.0, 2.0));
    float tipStrength = smoothstep(0.25, 0.75, hMain);
    color += tip * tipBand * tipStrength * 0.55;
  }

  /* ─── Vertical god-ray — soft column of light rising upward from each
       tall peak position, fading into the dark sky. Adds the "atmospheric
       beam" feel of a real lit voice visualizer. ───────────────────── */
  if (distMain < 0.0 && hMain > 0.20) {
    float colAbove = abs(distMain);
    float ray = exp(-pow(colAbove / 0.30, 1.3));
    float rayStrength = pow(hMain, 1.5);
    vec3 rayColor = mix(bandTop * 0.8, tip * 0.7, smoothstep(0.3, 0.9, hMain));
    color += rayColor * ray * rayStrength * 0.32;
  }

  /* ─── Soft horizontal bloom — at the envelope, neighboring pixels'
       brightness bleeds to this pixel. Approximated by sampling the wave
       height at a couple of offsets and adding a "skirt" of glow. ──── */
  {
    float blurStep = 0.022;
    float hL = waveHeight(uv.x - blurStep, 0.0);
    float hR = waveHeight(uv.x + blurStep, 0.0);
    float envYL = 0.85 - hL * 0.30;
    float envYR = 0.85 - hR * 0.30;
    float distL = abs(uv.y - envYL);
    float distR = abs(uv.y - envYR);
    float bloom = exp(-pow(distL / 0.10, 2.0)) + exp(-pow(distR / 0.10, 2.0));
    color += bandBottom * bloom * 0.06 * max(hL, hR);
  }

  /* Subtle grain so no region reads perfectly flat */
  color += (hash21(uv * uResolution + uTime * 0.001) - 0.5) * 0.012;

  /* Tone map → final */
  color = tonemap(color * 1.0);
  fragColor = vec4(color, 1.0);
}
`;

function compileShader(
  gl: WebGL2RenderingContext,
  type: number,
  src: string,
): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error("createShader failed");
  gl.shaderSource(shader, src);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(
      `Shader compile error (${type === gl.VERTEX_SHADER ? "vert" : "frag"}): ${log}`,
    );
  }
  return shader;
}

function linkProgram(
  gl: WebGL2RenderingContext,
  vert: WebGLShader,
  frag: WebGLShader,
): WebGLProgram {
  const program = gl.createProgram();
  if (!program) throw new Error("createProgram failed");
  gl.attachShader(program, vert);
  gl.attachShader(program, frag);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const log = gl.getProgramInfoLog(program);
    gl.deleteProgram(program);
    throw new Error(`Program link error: ${log}`);
  }
  return program;
}

export function VoiceGradient({ mode, spectrum }: VoiceGradientProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const modeRef = useRef<VoiceMode>(mode);
  const fadeRef = useRef(mode === "gaia" ? 1 : 0);

  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl2", {
      premultipliedAlpha: false,
      antialias: false,
      preserveDrawingBuffer: false,
    });
    if (!gl) {
      console.warn("[VoiceGradient] WebGL2 not supported");
      return;
    }

    let program: WebGLProgram;
    let vbo: WebGLBuffer | null = null;
    try {
      const vert = compileShader(gl, gl.VERTEX_SHADER, VERT);
      const frag = compileShader(gl, gl.FRAGMENT_SHADER, FRAG);
      program = linkProgram(gl, vert, frag);
      gl.deleteShader(vert);
      gl.deleteShader(frag);
    } catch (e) {
      console.error("[VoiceGradient] shader build failed", e);
      return;
    }

    vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );
    const aPos = gl.getAttribLocation(program, "aPos");
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    const uSpectrum = gl.getUniformLocation(program, "uSpectrum");
    const uTime = gl.getUniformLocation(program, "uTime");
    const uResolution = gl.getUniformLocation(program, "uResolution");
    const uMode = gl.getUniformLocation(program, "uMode");

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      gl.viewport(0, 0, canvas.width, canvas.height);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    const start = performance.now();
    let raf = 0;
    const draw = (now: number) => {
      const t = now - start;

      const target = modeRef.current === "gaia" ? 1 : 0;
      fadeRef.current += (target - fadeRef.current) * 0.06;

      // biome-ignore lint/correctness/useHookAtTopLevel: gl.useProgram is a WebGL call, not a React hook
      gl.useProgram(program);
      gl.uniform1fv(uSpectrum, spectrum);
      gl.uniform1f(uTime, t);
      gl.uniform2f(uResolution, canvas.width, canvas.height);
      gl.uniform1f(uMode, fadeRef.current);

      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLES, 0, 6);

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      if (vbo) gl.deleteBuffer(vbo);
      gl.deleteProgram(program);
    };
  }, [spectrum]);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0 h-full w-full"
    />
  );
}
