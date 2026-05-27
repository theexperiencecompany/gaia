/**
 * Fixed-capacity Float32 ring buffer. Lock-free single-producer / single-consumer.
 * Used to bridge AudioWorklet (producer) and inference loop (consumer) without
 * GC pressure or allocations on the hot path.
 */
export class RingBuffer {
  private readonly buffer: Float32Array;
  private writeIdx = 0;
  private readIdx = 0;
  private filled = 0;

  constructor(public readonly capacity: number) {
    this.buffer = new Float32Array(capacity);
  }

  get available(): number {
    return this.filled;
  }

  get free(): number {
    return this.capacity - this.filled;
  }

  write(chunk: Float32Array): number {
    const toWrite = Math.min(chunk.length, this.free);
    if (toWrite === 0) return 0;
    const firstPart = Math.min(toWrite, this.capacity - this.writeIdx);
    this.buffer.set(chunk.subarray(0, firstPart), this.writeIdx);
    if (firstPart < toWrite) {
      this.buffer.set(chunk.subarray(firstPart, toWrite), 0);
    }
    this.writeIdx = (this.writeIdx + toWrite) % this.capacity;
    this.filled += toWrite;
    return toWrite;
  }

  /**
   * Read exactly `length` samples into `out`. Returns false if not enough data.
   * Does not allocate.
   */
  read(out: Float32Array, length: number): boolean {
    if (this.filled < length) return false;
    const firstPart = Math.min(length, this.capacity - this.readIdx);
    out.set(this.buffer.subarray(this.readIdx, this.readIdx + firstPart), 0);
    if (firstPart < length) {
      out.set(this.buffer.subarray(0, length - firstPart), firstPart);
    }
    this.readIdx = (this.readIdx + length) % this.capacity;
    this.filled -= length;
    return true;
  }

  reset(): void {
    this.writeIdx = 0;
    this.readIdx = 0;
    this.filled = 0;
  }
}
