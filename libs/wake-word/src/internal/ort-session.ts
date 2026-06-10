import type { InferenceSession, TypedTensor } from "../types/index";

type TensorData = Float32Array | BigInt64Array | Int32Array;

/** Minimal structural view of an onnxruntime Tensor. */
interface OrtTensorLike {
  data: unknown;
  dims: readonly number[];
  type: string;
}

/** Minimal structural view of an onnxruntime Tensor constructor. */
interface OrtTensorCtor {
  new (
    type: TypedTensor["type"],
    data: TensorData,
    dims: number[],
  ): OrtTensorLike;
}

/** Minimal structural view of an onnxruntime InferenceSession. */
interface OrtRunSession {
  readonly inputNames: readonly string[];
  readonly outputNames: readonly string[];
  run(
    feeds: Record<string, OrtTensorLike>,
  ): Promise<Record<string, OrtTensorLike>>;
  release(): Promise<void>;
}

/**
 * Shared `InferenceSession` wrapper for the web and React Native adapters.
 * `onnxruntime-web` and `onnxruntime-react-native` expose the same session +
 * Tensor API, so the feed/result conversion lives here once instead of being
 * copied into each adapter.
 */
export class OrtSession implements InferenceSession {
  constructor(
    private readonly session: OrtRunSession,
    private readonly tensorCtor: OrtTensorCtor,
  ) {}

  inputNames(): readonly string[] {
    return this.session.inputNames;
  }

  outputNames(): readonly string[] {
    return this.session.outputNames;
  }

  async run(
    feeds: Record<string, TypedTensor>,
  ): Promise<Record<string, TypedTensor>> {
    const ortFeeds: Record<string, OrtTensorLike> = {};
    for (const [name, t] of Object.entries(feeds)) {
      ortFeeds[name] = new this.tensorCtor(t.type, t.data, t.dims as number[]);
    }
    const out = await this.session.run(ortFeeds);
    const result: Record<string, TypedTensor> = {};
    for (const [name, tensor] of Object.entries(out)) {
      result[name] = {
        data: tensor.data as TensorData,
        dims: tensor.dims,
        type: tensor.type as TypedTensor["type"],
      };
    }
    return result;
  }

  async release(): Promise<void> {
    await this.session.release();
  }
}

export function float32Tensor(
  data: Float32Array,
  dims: readonly number[],
): TypedTensor {
  return { data, dims, type: "float32" };
}

export function int64Tensor(
  value: bigint | number,
  dims: readonly number[] = [],
): TypedTensor {
  const v = typeof value === "bigint" ? value : BigInt(value);
  return { data: new BigInt64Array([v]), dims, type: "int64" };
}
