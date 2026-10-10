import type { z } from "zod";
import type { imageGallerySchema } from "../promptSpecs";
import { GalleryImage } from "./GalleryImage";

const GALLERY_COLS: Record<number, string> = {
  1: "grid-cols-1",
  2: "grid-cols-2",
  3: "grid-cols-3",
  4: "grid-cols-4",
  5: "grid-cols-5",
  6: "grid-cols-6",
};

function defaultGalleryCols(n: number): number {
  if (n <= 1) return 1;
  if (n === 2) return 2;
  if (n === 3) return 3;
  return 2;
}

const GALLERY_GAP: Record<
  NonNullable<z.infer<typeof imageGallerySchema>["gap"]>,
  string
> = {
  xs: "gap-1",
  sm: "gap-2",
  md: "gap-3",
  lg: "gap-5",
};

const GALLERY_MAX_W: Record<
  NonNullable<z.infer<typeof imageGallerySchema>["maxWidth"]>,
  string
> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-xl",
  full: "max-w-full",
};

export function ImageGalleryView(props: z.infer<typeof imageGallerySchema>) {
  const images = props.images;
  const aspectRatio = props.aspectRatio ?? "3/2";
  const cols = props.columns ?? defaultGalleryCols(images.length);
  const gridCols = GALLERY_COLS[cols] ?? "grid-cols-2";
  const gap = GALLERY_GAP[props.gap ?? "md"];
  const maxW = GALLERY_MAX_W[props.maxWidth ?? "xl"];

  return (
    <div className={`grid ${gridCols} ${gap} w-full ${maxW}`}>
      {images.map((img) => (
        <GalleryImage key={img.src} img={img} aspectRatio={aspectRatio} />
      ))}
    </div>
  );
}
