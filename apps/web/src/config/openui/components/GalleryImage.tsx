import * as m from "motion/react-m";
import Image from "next/image";
import { useParams } from "next/navigation";
import { resolveArtifactSrc } from "@/features/chat/api/sessionFilesApi";

export function GalleryImage({
  img,
}: {
  img: { src: string; alt?: string; caption?: string };
}) {
  const params = useParams<{ id?: string }>();
  const src = resolveArtifactSrc(img.src, params?.id) ?? img.src;
  return (
    <m.div
      whileHover={{ scale: 1.02 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="relative flex items-center justify-center overflow-hidden rounded-xl bg-zinc-900"
    >
      {/* Remote LLM-provided URLs can't be allow-listed as remotePatterns,
          so the Next.js optimizer is bypassed with `unoptimized`. */}
      <Image
        src={src}
        alt={img.alt ?? ""}
        width={600}
        height={400}
        sizes="(max-width: 768px) 50vw, 33vw"
        className="h-auto max-h-[320px] w-auto max-w-full rounded-xl object-contain"
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
