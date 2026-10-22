// ImageBubble.tsx
import { Skeleton } from "@heroui/skeleton";
import Image from "next/image";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import type { ImageData } from "@/types/features/toolDataTypes";

interface ImageBubbleProps
  extends Pick<
    ChatBubbleBotProps,
    "text" | "loading" | "setOpenImage" | "setImageData"
  > {
  image_data?: ImageData;
}

export default function ImageBubble({
  text,
  loading,
  image_data,
  setOpenImage,
  setImageData,
}: ImageBubbleProps) {
  // Only use image_data for image information
  if (!image_data?.url && !loading) return null;

  return (
    <>
      <Skeleton
        className="mb-4 max-h-[320px] w-fit max-w-full overflow-hidden rounded-2xl"
        isLoaded={!loading && Boolean(image_data?.url)}
      >
        {image_data?.url && (
          <Image
            alt="Generated Image"
            className="mx-auto h-auto max-h-[320px] w-auto max-w-full cursor-pointer! rounded-2xl object-contain"
            height={500}
            width={500}
            src={image_data.url}
            onClick={() => {
              setOpenImage(true);
              setImageData({
                src: image_data.url,
                prompt: image_data.prompt || "",
                improvedPrompt: image_data.improved_prompt || "",
              });
            }}
          />
        )}
      </Skeleton>
      {text.trim() && (
        <div className="chat_bubble bg-zinc-800">
          <span>{text}</span>
        </div>
      )}
    </>
  );
}
