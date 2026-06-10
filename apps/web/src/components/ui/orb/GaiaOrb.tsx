"use client";

import { useEffect, useRef } from "react";

/**
 * Visual states of the orb. Mirrors the voice-mode agent states so the
 * assistant popup (and later voice mode itself) can drive it directly.
 */
export type GaiaOrbState = "idle" | "listening" | "thinking" | "speaking";

interface GaiaOrbProps {
  state?: GaiaOrbState;
  className?: string;
}

/** Per-state shader energy targets, smoothly interpolated on transition. */
const STATE_TARGETS: Record<
  GaiaOrbState,
  { intensity: number; turbulence: number; pulse: number }
> = {
  idle: { intensity: 0.35, turbulence: 0.45, pulse: 0 },
  listening: { intensity: 0.9, turbulence: 0.75, pulse: 0.18 },
  thinking: { intensity: 0.7, turbulence: 2.1, pulse: 0 },
  speaking: { intensity: 1.0, turbulence: 1.1, pulse: 1.0 },
};

/** Exponential smoothing rate for state transitions (per second). */
const TRANSITION_RATE = 3.2;

/** Cap device pixel ratio to keep the fragment load reasonable. */
const MAX_DPR = 2;

const VERTEX_SHADER = `#version 300 es
void main() {
  // Fullscreen triangle, no buffers needed.
  vec2 pos = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  gl_Position = vec4(pos * 2.0 - 1.0, 0.0, 1.0);
}`;

const FRAGMENT_SHADER = `#version 300 es
precision highp float;

uniform vec2 u_resolution;
uniform float u_time;
uniform float u_intensity;  // overall energy 0..1
uniform float u_turbulence; // swirl speed multiplier
uniform float u_pulse;      // speaking throb 0..1
uniform float u_seed;

out vec4 fragColor;

// ---------------------------------------------------------------------------
// Value noise + fbm (hash-based, no textures)
// ---------------------------------------------------------------------------
float hash(vec3 p) {
  p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419) + u_seed);
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(vec3 x) {
  vec3 i = floor(x);
  vec3 f = fract(x);
  f = f * f * f * (f * (f * 6.0 - 15.0) + 10.0); // quintic fade
  return mix(
    mix(mix(hash(i + vec3(0, 0, 0)), hash(i + vec3(1, 0, 0)), f.x),
        mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
    mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x),
        mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y),
    f.z);
}

float fbm(vec3 p) {
  float sum = 0.0;
  float amp = 0.52;
  for (int i = 0; i < 5; i++) {
    sum += amp * noise(p);
    p = p * 2.03 + vec3(1.7, 9.2, 4.1);
    amp *= 0.5;
  }
  return sum;
}

// ---------------------------------------------------------------------------
// Palette
// ---------------------------------------------------------------------------
const vec3 DEEP = vec3(0.000, 0.110, 0.240);   // abyssal blue
const vec3 BRAND = vec3(0.000, 0.733, 1.000);  // #00bbff
const vec3 TURQ = vec3(0.290, 0.960, 0.860);   // turquoise wisps
const vec3 WHITE = vec3(1.0);

void main() {
  vec2 uv = (gl_FragCoord.xy * 2.0 - u_resolution) / min(u_resolution.x, u_resolution.y);
  float r = length(uv);
  float t = u_time;

  const float R = 0.62; // sphere radius in normalized units

  // Speaking throb: gentle radial breathing of every layer.
  float throb = 1.0 + u_pulse * 0.06 * sin(t * 7.0) + u_pulse * 0.03 * sin(t * 13.7);
  float rr = r / throb;

  // Sphere depth (fake 3rd coordinate) and soft edge mask.
  float z2 = R * R - rr * rr;
  float z = sqrt(max(z2, 0.0));
  float sphere = smoothstep(R, R - 0.035, rr);

  // Slow tumbling rotation of the noise domain.
  float ang = t * 0.12 * (0.4 + u_turbulence);
  mat2 rot = mat2(cos(ang), -sin(ang), sin(ang), cos(ang));
  vec3 sp = vec3(rot * uv, z);

  // Two-level domain warp — this is what makes the wisps feel alive.
  vec3 flow = sp * 2.2 + vec3(0.0, t * 0.05, t * 0.22 * (0.5 + u_turbulence * 0.5));
  vec3 warp = vec3(
    fbm(flow + vec3(0.0, 3.1, 1.3)),
    fbm(flow.zxy + vec3(t * 0.07, 0.0, 5.7)),
    fbm(flow.yzx + vec3(2.4, t * 0.05, 0.0)));
  float field = fbm(flow + 1.6 * warp);

  // Broad turquoise wisps and fine white filaments.
  float wisp = smoothstep(0.32, 0.86, field);
  float fil = smoothstep(0.60, 0.92, fbm(sp * 4.8 + warp * 2.2 + vec3(0.0, 0.0, t * 0.35)));

  // Fresnel rim — bright limb where the sphere curves away.
  float fres = pow(1.0 - clamp(z / R, 0.0, 1.0), 2.6);

  // Compose interior color.
  vec3 col = mix(DEEP, BRAND, 0.45 + 0.55 * wisp);
  col = mix(col, TURQ, wisp * wisp * 0.60);
  col += WHITE * fil * (0.28 + 0.60 * u_intensity);
  col += BRAND * fres * (0.40 + 0.35 * u_intensity);
  col += TURQ * pow(fres, 3.0) * 0.45;

  // Inner core glow, breathing slowly.
  float core = exp(-rr * rr * 5.0);
  col += mix(BRAND, WHITE, 0.40) * core * (0.30 + 0.55 * u_intensity) * (0.8 + 0.2 * sin(t * 1.1));

  // Energy scale.
  col *= 0.70 + 0.60 * u_intensity;

  float alpha = sphere;

  // Outer halo — noise-modulated glow bleeding onto the glass.
  float haloFall = exp(-pow(max(rr - R + 0.04, 0.0) * 4.6, 1.35));
  float haloNoise = 0.75 + 0.25 * fbm(vec3(uv * 2.0, t * 0.18));
  float halo = haloFall * haloNoise * (1.0 - sphere);
  vec3 haloCol = mix(BRAND, TURQ, 0.5 + 0.5 * sin(t * 0.23)) * halo;
  col += haloCol * (0.40 + 0.55 * u_intensity + 0.50 * u_pulse * (0.6 + 0.4 * sin(t * 7.0)));
  alpha = max(alpha, halo * (0.50 + 0.40 * u_intensity));

  // Premultiplied alpha output for clean compositing over vibrancy/glass.
  fragColor = vec4(col * alpha, alpha);
}`;

function compile(gl: WebGL2RenderingContext, type: number, source: string) {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error(
      "[GaiaOrb] Shader compile error:",
      gl.getShaderInfoLog(shader),
    );
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

/**
 * Plain (non-React) WebGL2 renderer: compiles the shader, owns the
 * render loop, and tracks canvas size. Reads the live state targets via
 * `getTarget` each frame and eases toward them.
 *
 * @returns A dispose function, or `null` if WebGL2 is unavailable.
 */
function createOrbRenderer(
  canvas: HTMLCanvasElement,
  getTarget: () => { intensity: number; turbulence: number; pulse: number },
): (() => void) | null {
  const gl = canvas.getContext("webgl2", {
    alpha: true,
    premultipliedAlpha: true,
    antialias: false,
    depth: false,
    stencil: false,
  });
  if (!gl) {
    console.error("[GaiaOrb] WebGL2 unavailable");
    return null;
  }

  const vs = compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
  const fs = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
  if (!vs || !fs) return null;
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error(
      "[GaiaOrb] Program link error:",
      gl.getProgramInfoLog(program),
    );
    return null;
  }
  // biome-ignore lint/correctness/useHookAtTopLevel: gl.useProgram is a WebGL call, not a React hook
  gl.useProgram(program);

  const uniforms = {
    resolution: gl.getUniformLocation(program, "u_resolution"),
    time: gl.getUniformLocation(program, "u_time"),
    intensity: gl.getUniformLocation(program, "u_intensity"),
    turbulence: gl.getUniformLocation(program, "u_turbulence"),
    pulse: gl.getUniformLocation(program, "u_pulse"),
    seed: gl.getUniformLocation(program, "u_seed"),
  };
  gl.uniform1f(uniforms.seed, Math.random() * 100);

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
    const width = Math.max(1, Math.round(canvas.clientWidth * dpr));
    const height = Math.max(1, Math.round(canvas.clientHeight * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
  };
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  resize();

  const current = { ...getTarget() };
  let raf = 0;
  let last = performance.now();
  const start = last;

  const frame = (now: number) => {
    raf = requestAnimationFrame(frame);
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;

    // Smooth, frame-rate-independent approach to the state targets.
    const target = getTarget();
    const k = 1 - Math.exp(-dt * TRANSITION_RATE);
    current.intensity += (target.intensity - current.intensity) * k;
    current.turbulence += (target.turbulence - current.turbulence) * k;
    current.pulse += (target.pulse - current.pulse) * k;

    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(uniforms.resolution, canvas.width, canvas.height);
    gl.uniform1f(uniforms.time, (now - start) / 1000);
    gl.uniform1f(uniforms.intensity, current.intensity);
    gl.uniform1f(uniforms.turbulence, current.turbulence);
    gl.uniform1f(uniforms.pulse, current.pulse);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };
  raf = requestAnimationFrame(frame);

  const handleVisibility = () => {
    cancelAnimationFrame(raf);
    if (document.visibilityState === "visible") {
      last = performance.now();
      raf = requestAnimationFrame(frame);
    }
  };
  document.addEventListener("visibilitychange", handleVisibility);

  return () => {
    cancelAnimationFrame(raf);
    document.removeEventListener("visibilitychange", handleVisibility);
    observer.disconnect();
    gl.deleteProgram(program);
    gl.deleteShader(vs);
    gl.deleteShader(fs);
  };
}

/**
 * GAIA's orb — a from-scratch WebGL2 plasma sphere in the brand palette:
 * deep blue body, #00bbff energy, turquoise wisps, white filaments, and a
 * glow halo that bleeds onto the surface behind it. Renders with
 * premultiplied alpha so it composites directly onto liquid glass /
 * vibrancy backgrounds with no containing card.
 */
export default function GaiaOrb({ state = "idle", className }: GaiaOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef<GaiaOrbState>(state);
  stateRef.current = state;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dispose = createOrbRenderer(
      canvas,
      () => STATE_TARGETS[stateRef.current],
    );
    return () => dispose?.();
  }, []);

  return <canvas ref={canvasRef} className={className} />;
}
