import { readFileSync } from "node:fs";
// @ts-expect-error — wavefile ships its own types but tsconfig with node-types
import { WaveFile } from "wavefile";

/** Read a WAV file from disk and return mono 16 kHz float32 samples in [-1, 1]. */
export function readWavMono16k(path: string): Float32Array {
  const wav = new WaveFile(readFileSync(path));
  wav.toBitDepth("32f");
  if (wav.fmt.sampleRate !== 16000) {
    throw new Error(
      `expected 16000 Hz wav, got ${String(wav.fmt.sampleRate)} at ${path}`,
    );
  }
  const raw = wav.getSamples(false);
  // getSamples returns Float64Array for mono or [Float64Array, Float64Array] for stereo.
  let samples: Float32Array;
  if (raw instanceof Float64Array || raw instanceof Float32Array) {
    samples = new Float32Array(raw);
  } else if (Array.isArray(raw)) {
    const channels = raw as (Float64Array | Float32Array)[];
    const len = channels[0]?.length ?? 0;
    samples = new Float32Array(len);
    for (let i = 0; i < len; i++) {
      let acc = 0;
      for (const ch of channels) acc += ch[i] ?? 0;
      samples[i] = acc / channels.length;
    }
  } else {
    throw new Error("wavefile returned unsupported sample shape");
  }
  return samples;
}
