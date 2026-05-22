/**
 * Browser / Electron runtime adapter. Wraps `onnxruntime-web`.
 *
 * Consumers must install `onnxruntime-web` themselves (it is a peer dep), and
 * also serve the ORT WASM artifacts from a public path. See the README for
 * Next.js / Vite / Webpack setup.
 */

import type * as ortType from "onnxruntime-web";
import {
  float32Tensor,
  int64Tensor,
  OrtSession,
} from "../internal/ort-session";
import type {
  InferenceRuntime,
  InferenceSession,
  ModelSource,
  TypedTensor,
} from "../types/index";

type OrtModule = typeof ortType;

let ortPromise: Promise<OrtModule> | null = null;
function getOrt(): Promise<OrtModule> {
  if (!ortPromise) {
    ortPromise = (
      import(/* @vite-ignore */ "onnxruntime-web") as Promise<OrtModule>
    ).catch((err) => {
      // Don't cache a rejected import — let the next call retry.
      ortPromise = null;
      throw err;
    });
  }
  return ortPromise;
}

// `ort.env.wasm` is global, module-wide state shared by every InferenceSession
// and must be set before the first session is created. Configure it exactly
// once so multiple WebRuntime instances can't overwrite each other.
let ortWasmConfigured = false;
function configureOrtWasm(ort: OrtModule, opts: WebRuntimeOptions): void {
  if (ortWasmConfigured) return;
  ortWasmConfigured = true;
  if (opts.wasmPaths) ort.env.wasm.wasmPaths = opts.wasmPaths;
  if (typeof opts.numThreads === "number") {
    ort.env.wasm.numThreads = opts.numThreads;
  } else if (typeof navigator !== "undefined") {
    const cores = navigator.hardwareConcurrency ?? 2;
    ort.env.wasm.numThreads = Math.max(1, Math.min(4, Math.floor(cores / 2)));
  }
  if (opts.simd !== undefined) ort.env.wasm.simd = opts.simd;
}

export interface WebRuntimeOptions {
  /** Where to fetch ORT WASM artifacts from. Defaults to onnxruntime-web's CDN. */
  wasmPaths?: string;
  /** Preferred execution providers in order. Defaults to ["wasm"]. */
  executionProviders?: ortType.InferenceSession.ExecutionProviderConfig[];
  /** Number of WASM threads. Defaults to navigator.hardwareConcurrency clamped to 4. */
  numThreads?: number;
  /** Enable SIMD when supported (default true). */
  simd?: boolean;
}

export class WebRuntime implements InferenceRuntime {
  constructor(private readonly opts: WebRuntimeOptions = {}) {}

  async loadSession(source: ModelSource): Promise<InferenceSession> {
    const ort = await getOrt();
    configureOrtWasm(ort, this.opts);

    let bytes: Uint8Array;
    if (source.kind === "url") {
      const res = await fetch(source.url);
      if (!res.ok) throw new Error(`fetch ${source.url} → ${res.status}`);
      bytes = new Uint8Array(await res.arrayBuffer());
    } else if (source.kind === "bytes") {
      bytes =
        source.bytes instanceof Uint8Array
          ? source.bytes
          : new Uint8Array(source.bytes);
    } else {
      throw new Error("WebRuntime does not support 'asset' model sources");
    }
    const session = await ort.InferenceSession.create(bytes, {
      executionProviders: this.opts.executionProviders ?? ["wasm"],
      graphOptimizationLevel: "all",
    });
    return new OrtSession(session, ort.Tensor);
  }

  tensor(data: Float32Array, dims: readonly number[]): TypedTensor {
    return float32Tensor(data, dims);
  }

  int64(value: bigint | number, dims: readonly number[] = []): TypedTensor {
    return int64Tensor(value, dims);
  }
}
