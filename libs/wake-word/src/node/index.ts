/**
 * Node.js runtime adapter. Used for tests and CLI tooling only — not shipped
 * with browser/electron/RN bundles. Wraps `onnxruntime-node`.
 */

import { readFile } from "node:fs/promises";
import * as ort from "onnxruntime-node";
import type {
  InferenceRuntime,
  InferenceSession,
  ModelSource,
  TypedTensor,
} from "../types/index";

class NodeSession implements InferenceSession {
  constructor(private readonly s: ort.InferenceSession) {}
  inputNames(): readonly string[] {
    return this.s.inputNames;
  }
  outputNames(): readonly string[] {
    return this.s.outputNames;
  }
  async run(
    feeds: Record<string, TypedTensor>,
  ): Promise<Record<string, TypedTensor>> {
    const ortFeeds: Record<string, ort.Tensor> = {};
    for (const [name, t] of Object.entries(feeds)) {
      ortFeeds[name] = toOrtTensor(t);
    }
    const out = await this.s.run(ortFeeds);
    const result: Record<string, TypedTensor> = {};
    for (const [name, tensor] of Object.entries(out)) {
      result[name] = fromOrtTensor(tensor);
    }
    return result;
  }
  async release(): Promise<void> {
    await this.s.release();
  }
}

function toOrtTensor(t: TypedTensor): ort.Tensor {
  if (t.type === "float32") {
    return new ort.Tensor(
      "float32",
      t.data as Float32Array,
      t.dims as number[],
    );
  }
  if (t.type === "int64") {
    return new ort.Tensor("int64", t.data as BigInt64Array, t.dims as number[]);
  }
  if (t.type === "int32") {
    return new ort.Tensor("int32", t.data as Int32Array, t.dims as number[]);
  }
  throw new Error(`Unsupported tensor type: ${String(t.type)}`);
}

function fromOrtTensor(t: ort.Tensor): TypedTensor {
  if (t.type === "float32") {
    return { data: t.data as Float32Array, dims: t.dims, type: "float32" };
  }
  if (t.type === "int64") {
    return { data: t.data as BigInt64Array, dims: t.dims, type: "int64" };
  }
  if (t.type === "int32") {
    return { data: t.data as Int32Array, dims: t.dims, type: "int32" };
  }
  throw new Error(`Unsupported ORT tensor type: ${t.type}`);
}

export class NodeRuntime implements InferenceRuntime {
  async loadSession(source: ModelSource): Promise<InferenceSession> {
    let bytes: Uint8Array;
    if (source.kind === "url") {
      const res = await fetch(source.url);
      if (!res.ok) throw new Error(`fetch ${source.url} → ${res.status}`);
      bytes = new Uint8Array(await res.arrayBuffer());
    } else if (source.kind === "asset") {
      bytes = new Uint8Array(await readFile(String(source.asset)));
    } else {
      bytes =
        source.bytes instanceof Uint8Array
          ? source.bytes
          : new Uint8Array(source.bytes);
    }
    const session = await ort.InferenceSession.create(bytes, {
      executionProviders: ["cpu"],
      graphOptimizationLevel: "all",
    });
    return new NodeSession(session);
  }

  tensor(data: Float32Array, dims: readonly number[]): TypedTensor {
    return { data, dims, type: "float32" };
  }

  int64(value: bigint | number, dims: readonly number[] = []): TypedTensor {
    const v = typeof value === "bigint" ? value : BigInt(value);
    return { data: new BigInt64Array([v]), dims, type: "int64" };
  }
}
