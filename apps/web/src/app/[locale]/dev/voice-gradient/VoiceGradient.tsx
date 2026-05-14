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

/* ─── Trivial blit fragment: samples the wave FBO with bilinear filter ── */
const BLIT_FRAG = /* glsl */ `#version 300 es
precision highp float;
in vec2 vUv;
out vec4 fragColor;
uniform sampler2D uTex;
void main() {
  fragColor = texture(uTex, vUv);
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
  /* 3 octaves is enough for the visual texture we need — 4 octaves was
     ~33% more fragment work for sub-pixel detail nobody sees through
     the heavy gaussian/blur passes. */
  float v = 0.0;
  float a = 0.55;
  for (int i = 0; i < 3; i++) {
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
    a phase-shifted slice of the spectrum so each ghost has its own shape.
    Peak-sharpening: we sample the bin at fi AND its neighbours; if fi
    is a local maximum, we BOOST it (peak rises higher than its shoulders),
    yielding pointed mountain peaks instead of plateaus. */
float waveHeight(float xNorm, float binShift) {
  /* Drifting-center mapping — wanders ±0.15 around mid-screen so the
     action stays roughly centered but never exactly mirrored. */
  float driftCenter = 0.5 +
    sin(uTime * 0.00018) * 0.11 +
    sin(uTime * 0.00027 + 1.7) * 0.05;

  /* Per-x fBM bin-index jitter — too big causes aliased vertical pillars
     (adjacent x's land on completely different bins). Keep moderate. */
  float binJitter =
    (fbm(vec2(xNorm * 4.5 + binShift * 0.7,
              uTime * 0.00009)) - 0.5) * 2.8;

  /* Smoothly-varying side-bias: tanh maps xRel through a continuous S-curve
     from -1.5 (far left) to +2.5 (far right) — same |xRel| samples different
     bins on each side, but with NO discontinuity at xRel=0 (which would
     otherwise produce a vertical pillar artifact through the drift center). */
  float xRel = xNorm - driftCenter;
  float sideBias = 0.5 + 2.0 * tanh(xRel * 10.0);

  float centerDist = abs(xRel) * 2.0;
  float fi = centerDist * float(${SPECTRUM_BINS} - 1)
           + binShift + binJitter + sideBias;
  fi = max(0.0, fi);

  float v  = specAt(fi);
  float vL = specAt(max(0.0, fi - 0.7));
  float vR = specAt(fi + 0.7);

  /* Local-maxima boost — peaks rise more than their shoulders. */
  float ridge = max(0.0, v - 0.5 * (vL + vR));
  v = v + ridge * 1.1;

  /* Gamma curve — crushes low/mid energy so peaks spike visibly. */
  v = pow(clamp(v, 0.0, 1.4), 2.3);

  /* Small height-domain perturbation to add organic micro-roughness. */
  float perturb = (fbm(vec2(xNorm * 5.0 + binShift,
                            uTime * 0.00013)) - 0.5) * 0.05;
  return clamp(v + perturb, 0.0, 1.0);
}

void main() {
  vec2 uv = vUv;
  // Flip y so top of canvas = 0, bottom = 1 (matches our mental model).
  uv.y = 1.0 - uv.y;
  float aspect = uResolution.x / uResolution.y;

  /* ─── Palette ───────────────────────────────────────────────────────── */
  /* User mode (cool slate / white), GAIA mode (deep navy / muted blue).
     Top stop kept dark so the wave's vertical extent matches GAIA mode
     in perceived height — brighter colors at the upper edge would make
     the wave read as taller even when geometry is identical. */
  vec3 bandBottomU = vec3(0.78, 0.85, 0.96);
  vec3 bandTopU    = vec3(0.08, 0.10, 0.18);
  vec3 navyU       = vec3(0.05, 0.08, 0.16);
  vec3 tipU        = vec3(0.92, 0.95, 1.00);

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

  /* Same wave geometry in both modes — palette is the only thing that
     differs across modes. ampMul stays at 1.0. */
  float ampMul = 1.0;

  /* Far back ghost — very wide feather, low alpha, dark blue */
  {
    float h = waveHeight(uv.x, 4.0) * ampMul;
    float yBase = 0.68 - h * 0.34;
    float dist = uv.y - yBase;
    float mask = 0.5 + 0.5 * tanh(dist / 0.20 * 1.6);
    vec3 col = mix(bandTop * 0.5, bandTop, smoothstep(0.0, 0.6, dist));
    col *= 0.5 + density * 1.1;
    color += col * mask * 0.45;
  }

  /* Mid ghost */
  {
    float h = waveHeight(uv.x, 1.8) * ampMul;
    float yBase = 0.76 - h * 0.34;
    float dist = uv.y - yBase;
    float mask = 0.5 + 0.5 * tanh(dist / 0.14 * 1.7);
    vec3 col = mix(bandTop, mix(bandTop, bandBottom, 0.55), smoothstep(0.0, 0.4, dist));
    col *= 0.5 + density * 1.2;
    color += col * mask * 0.6;
  }

  /* Foreground — sharper, brightest body. ampMul (declared above) scales
     user-mode wave height down ~15% so the brighter white palette doesn't
     read as visually taller than GAIA's blue. */
  /* Cached centre-x wave height — reused by body fill, radial glow,
     chromatic tip and bloom passes to avoid 3+ redundant fragment ops
     per pixel. */
  float hRaw = waveHeight(uv.x, 0.0);
  float hMain = hRaw * ampMul;
  float envY = 0.87 - hMain * 0.34;
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

  /* ─── Radial peak glow. Strength uses a HORIZONTAL-AVERAGED hMain so
       neighbouring x's don't snap to different glow intensities (which
       would manifest as vertical pillars). ─────────────────────────── */
  {
    float dist = abs(distMain);
    float hAvg = (waveHeight(uv.x - 0.05, 0.0)
                + hRaw * 2.0
                + waveHeight(uv.x + 0.05, 0.0)) * 0.25 * ampMul;
    float glow = exp(-pow(dist / 0.18, 1.4));
    float strength = pow(hAvg, 1.2);
    vec3 glowColor = mix(bandBottom * 1.2, tip, smoothstep(0.4, 1.0, hAvg));
    color += glowColor * glow * strength * 0.5;
  }

  /* ─── Chromatic peak tip — narrow cyan-green band right AT the envelope.
       Only fires on tall peaks so the colour dispersion reads as "lit
       lens" at the summit rather than smearing across the whole band. */
  {
    /* Chromatic tip — heavily horizontal-averaged + low intensity so it
       stays a subtle iridescent shimmer at peak summits, not a column. */
    float hTip = (waveHeight(uv.x - 0.06, 0.0)
                + waveHeight(uv.x - 0.03, 0.0) * 2.0
                + hRaw * 3.0
                + waveHeight(uv.x + 0.03, 0.0) * 2.0
                + waveHeight(uv.x + 0.06, 0.0)) * (1.0 / 9.0) * ampMul;
    float tipBand = exp(-pow(distMain * 26.0, 2.0));
    float tipStrength = smoothstep(0.22, 0.7, hTip);
    color += tip * tipBand * tipStrength * 0.18;
  }

  /* (God-ray pass removed — its per-pixel-x evaluation produced visible
     vertical pillars at every peak position. The body fill, peak radial
     glow, atmospheric halo and bloom skirt below carry the "lit" feel
     without the column artifacts.) */

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

    let waveProgram: WebGLProgram;
    let blitProgram: WebGLProgram;
    let vbo: WebGLBuffer | null = null;
    try {
      const vert = compileShader(gl, gl.VERTEX_SHADER, VERT);
      const wfrag = compileShader(gl, gl.FRAGMENT_SHADER, FRAG);
      const bfrag = compileShader(gl, gl.FRAGMENT_SHADER, BLIT_FRAG);
      waveProgram = linkProgram(gl, vert, wfrag);
      blitProgram = linkProgram(gl, vert, bfrag);
      gl.deleteShader(vert);
      gl.deleteShader(wfrag);
      gl.deleteShader(bfrag);
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
    /* Each program needs its own aPos binding because attribute locations
       are program-specific. */
    const bindAttribFor = (prog: WebGLProgram) => {
      const loc = gl.getAttribLocation(prog, "aPos");
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    };
    bindAttribFor(waveProgram);
    bindAttribFor(blitProgram);

    const uSpectrum = gl.getUniformLocation(waveProgram, "uSpectrum");
    const uTime = gl.getUniformLocation(waveProgram, "uTime");
    const uResolution = gl.getUniformLocation(waveProgram, "uResolution");
    const uMode = gl.getUniformLocation(waveProgram, "uMode");
    const uBlitTex = gl.getUniformLocation(blitProgram, "uTex");

    /* ─── Offscreen framebuffer: heavy wave shader renders into a
         half-resolution colour texture, then the trivial blit shader
         upsamples it to the canvas with bilinear filtering. The wave is
         volumetric/blurred so the 2× upscale is invisible, and the
         fragment-shader workload drops ~75%. */
    const fbo = gl.createFramebuffer();
    const fboTex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, fboTex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(
      gl.FRAMEBUFFER,
      gl.COLOR_ATTACHMENT0,
      gl.TEXTURE_2D,
      fboTex,
      0,
    );
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);

    /* Scale factor for the offscreen render relative to the canvas. */
    const RENDER_SCALE = 0.5;
    let fboW = 0;
    let fboH = 0;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      fboW = Math.max(2, Math.floor(canvas.width * RENDER_SCALE));
      fboH = Math.max(2, Math.floor(canvas.height * RENDER_SCALE));
      gl.bindTexture(gl.TEXTURE_2D, fboTex);
      gl.texImage2D(
        gl.TEXTURE_2D,
        0,
        gl.RGBA,
        fboW,
        fboH,
        0,
        gl.RGBA,
        gl.UNSIGNED_BYTE,
        null,
      );
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

      /* Pass 1 — render wave into the half-res FBO. */
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.viewport(0, 0, fboW, fboH);
      // biome-ignore lint/correctness/useHookAtTopLevel: gl.useProgram is a WebGL call, not a React hook
      gl.useProgram(waveProgram);
      bindAttribFor(waveProgram);
      gl.uniform1fv(uSpectrum, spectrum);
      gl.uniform1f(uTime, t);
      gl.uniform2f(uResolution, fboW, fboH);
      gl.uniform1f(uMode, fadeRef.current);
      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLES, 0, 6);

      /* Pass 2 — blit FBO texture to canvas at full resolution with
         bilinear upsampling (the GPU handles the interpolation for free). */
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.viewport(0, 0, canvas.width, canvas.height);
      // biome-ignore lint/correctness/useHookAtTopLevel: gl.useProgram is a WebGL call, not a React hook
      gl.useProgram(blitProgram);
      bindAttribFor(blitProgram);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, fboTex);
      gl.uniform1i(uBlitTex, 0);
      gl.drawArrays(gl.TRIANGLES, 0, 6);

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      if (vbo) gl.deleteBuffer(vbo);
      if (fbo) gl.deleteFramebuffer(fbo);
      if (fboTex) gl.deleteTexture(fboTex);
      gl.deleteProgram(waveProgram);
      gl.deleteProgram(blitProgram);
    };
  }, [spectrum]);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0 h-full w-full"
    />
  );
}
