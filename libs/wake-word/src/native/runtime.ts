/**
 * React Native runtime adapter. Wraps `onnxruntime-react-native`, which exposes
 * the same `InferenceSession` API as `onnxruntime-web` / `onnxruntime-node`,
 * backed by native iOS/Android ONNX kernels.
 *
 * Consumers install `onnxruntime-react-native` as a peer dep and bundle the
 * ONNX model files into their app assets. On iOS, add to `Info.plist`:
 *   NSMicrophoneUsageDescription
 * On Android (API 34+), declare a microphone foreground service:
 *   <service android:name=".WakeWordService"
 *            android:foregroundServiceType="microphone" />
 */

import type * as ortType from "onnxruntime-react-native";
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
      import(
        /* @vite-ignore */ "onnxruntime-react-native"
      ) as Promise<OrtModule>
    ).catch((err) => {
      // Don't cache a rejected import — let the next call retry.
      ortPromise = null;
      throw err;
    });
  }
  return ortPromise;
}

class NativeSession implements InferenceSession {
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

export class NativeRuntime implements InferenceRuntime {
  async loadSession(source: ModelSource): Promise<InferenceSession> {
    const ort = await getOrt();
    let session: ortType.InferenceSession;
    if (source.kind === "asset") {
      // onnxruntime-react-native accepts an asset path / require() id directly.
      session = await ort.InferenceSession.create(source.asset as string);
    } else if (source.kind === "url") {
      const res = await fetch(source.url);
      if (!res.ok) throw new Error(`fetch ${source.url} → ${res.status}`);
      const bytes = new Uint8Array(await res.arrayBuffer());
      session = await ort.InferenceSession.create(bytes);
    } else {
      const bytes =
        source.bytes instanceof Uint8Array
          ? source.bytes
          : new Uint8Array(source.bytes);
      session = await ort.InferenceSession.create(bytes);
    }
    return new NativeSession(session);
  }

  tensor(data: Float32Array, dims: readonly number[]): TypedTensor {
    return { data, dims, type: "float32" };
  }

  int64(value: bigint | number, dims: readonly number[] = []): TypedTensor {
    const v = typeof value === "bigint" ? value : BigInt(value);
    return { data: new BigInt64Array([v]), dims, type: "int64" };
  }
}
