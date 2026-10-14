/** Builds the leading bytes of a real PNG: the signature and an IHDR chunk. */
export function pngHeader(width: number, height: number): Buffer {
  const png = Buffer.alloc(33);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(png, 0);
  png.writeUInt32BE(13, 8);
  png.write("IHDR", 12, "ascii");
  png.writeUInt32BE(width, 16);
  png.writeUInt32BE(height, 20);
  png.writeUInt8(8, 24); // bit depth
  png.writeUInt8(6, 25); // colour type: RGBA
  return png;
}
