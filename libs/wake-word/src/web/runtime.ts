/**
 * Browser / Electron runtime adapter. Wraps `onnxruntime-web`.
 *
 * Consumers must install `onnxruntime-web` themselves (it is a peer dep), and
 * also serve the ORT WASM artifacts from a public path. See the README for
 * Next.js / Vite / Webpack setup.
 */

import type * as ortType from "onnxruntime-web";
import type {
  InferenceRuntime,
  InferenceSession,
  ModelSource,
  TypedTensor,
} from "../types/index.js";

type OrtModule = typeof ortType;

let ortPromise: Promise<OrtModule> | null = null;
function getOrt(): Promise<OrtModule> {
  if (!ortPromise) {
    ortPromise = import(
      /* @vite-ignore */ "onnxruntime-web"
    ) as Promise<OrtModule>;
  }
  return ortPromise;
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

class WebSession implements InferenceSession {
  constructor(private readonly s: ortType.InferenceSession) {}
  inputNames(): readonly string[] {
    return this.s.inputNames;
  }
  outputNames(): readonly string[] {
    return this.s.outputNames;
  }
  async run(
    feeds: Record<string, TypedTensor>,
  ): Promise<Record<string, TypedTensor>> {
    const ort = await getOrt();
    const ortFeeds: Record<string, ortType.Tensor> = {};
    for (const [name, t] of Object.entries(feeds)) {
      ortFeeds[name] = new ort.Tensor(
        t.type,
        t.data as Float32Array | BigInt64Array | Int32Array,
        t.dims as number[],
      );
    }
    const out = await this.s.run(ortFeeds);
    const result: Record<string, TypedTensor> = {};
    for (const [name, tensor] of Object.entries(out)) {
      result[name] = {
        data: tensor.data as Float32Array | BigInt64Array | Int32Array,
        dims: tensor.dims,
        type: tensor.type as TypedTensor["type"],
      };
    }
    return result;
  }
  async release(): Promise<void> {
    await this.s.release();
  }
}

export class WebRuntime implements InferenceRuntime {
  constructor(private readonly opts: WebRuntimeOptions = {}) {}

  async loadSession(source: ModelSource): Promise<InferenceSession> {
    const ort = await getOrt();
    if (this.opts.wasmPaths) ort.env.wasm.wasmPaths = this.opts.wasmPaths;
    if (typeof this.opts.numThreads === "number") {
      ort.env.wasm.numThreads = this.opts.numThreads;
    } else if (typeof navigator !== "undefined") {
      const cores = navigator.hardwareConcurrency ?? 2;
      ort.env.wasm.numThreads = Math.max(1, Math.min(4, Math.floor(cores / 2)));
    }
    if (this.opts.simd !== undefined) ort.env.wasm.simd = this.opts.simd;

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
    return new WebSession(session);
  }

  tensor(data: Float32Array, dims: readonly number[]): TypedTensor {
    return { data, dims, type: "float32" };
  }

  int64(value: bigint | number, dims: readonly number[] = []): TypedTensor {
    const v = typeof value === "bigint" ? value : BigInt(value);
    return { data: new BigInt64Array([v]), dims, type: "int64" };
  }
}
