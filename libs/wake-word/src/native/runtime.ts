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
    return new OrtSession(session, ort.Tensor);
  }

  tensor(data: Float32Array, dims: readonly number[]): TypedTensor {
    return float32Tensor(data, dims);
  }

  int64(value: bigint | number, dims: readonly number[] = []): TypedTensor {
    return int64Tensor(value, dims);
  }
}
