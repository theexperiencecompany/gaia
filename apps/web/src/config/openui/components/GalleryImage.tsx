import * as m from "motion/react-m";
import Image from "next/image";
import { useParams } from "next/navigation";
import { resolveArtifactSrc } from "@/features/chat/api/sessionFilesApi";

export function GalleryImage({
  img,
  aspectRatio = "3/2",
}: {
  img: { src: string; alt?: string; caption?: string };
  aspectRatio?: string;
}) {
  const params = useParams<{ id?: string }>();
  const src = resolveArtifactSrc(img.src, params?.id) ?? img.src;
  return (
    <m.div
      whileHover={{ scale: 1.02 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="relative overflow-hidden rounded-xl cursor-pointer"
      style={{ aspectRatio }}
    >
      {/* Remote LLM-provided URLs can't be allow-listed as remotePatterns,
          so the Next.js optimizer is bypassed with `unoptimized`. */}
      <Image
        src={src}
        alt={img.alt ?? ""}
        fill
        sizes="(max-width: 768px) 50vw, 33vw"
        className="object-cover"
        unoptimized
      />
      {img.caption && (
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-3 py-2 pointer-events-none">
          <p className="text-xs text-white/90 font-medium leading-snug">
            {img.caption}
          </p>
        </div>
      )}
    </m.div>
  );
}
