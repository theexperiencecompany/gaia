import Image from "next/image";

import { Sheet, SheetContent } from "@/components/ui/sheet";
import ChatBubble_Actions_Image from "@/features/chat/components/bubbles/actions/ChatBubble_Actions_Image";
import type { SetImageDataType } from "@/types/features/chatBubbleTypes";
import type { ImageData } from "@/types/features/convoTypes";

interface GeneratedImageSheetProps {
  openImage: boolean;
  setOpenImage?: React.Dispatch<React.SetStateAction<boolean>>;
  imageData?: SetImageDataType;
}

export default function GeneratedImageSheet({
  openImage,
  setOpenImage,
  imageData,
}: GeneratedImageSheetProps) {
  // Create a standard image_data object from imageData
  const image_data: ImageData = imageData
    ? {
        url: imageData.src,
        prompt: imageData.prompt,
        improved_prompt: imageData.improvedPrompt,
      }
    : { url: "" };

  return (
    <Sheet open={openImage} onOpenChange={setOpenImage}>
      <SheetContent className="flex max-w-(--breakpoint-sm) min-w-fit flex-col items-center rounded-3xl! border-none bg-zinc-900 px-5 py-3 text-white">
        <div className="relative mt-3 flex aspect-square w-full sm:w-screen sm:max-w-(--breakpoint-sm)">
          {imageData?.src && (
            <Image
              alt={"Generated Image"}
              className="my-2 aspect-square rounded-3xl"
              fill={true}
              src={imageData.src}
              objectFit="contain"
            />
          )}
        </div>

        <div className="mt-3 flex w-screen max-w-(--breakpoint-sm) flex-col justify-evenly gap-3">
          {/* {imageData?.prompt && (
            <div className="w-full">
              <ScrollArea className="max-h-[50px]">
                <div className="font-medium">Your Prompt:</div>

                <div className="text-sm text-foreground-500">
                  {imageData.prompt}
                </div>
              </ScrollArea>
            </div>
          )}
          {imageData?.improvedPrompt && (
            <div className="w-full">
              <ScrollArea className="h-[70px]">
                <div className="font-medium">Improved Prompt:</div>
                <div className="text-sm text-foreground-500">
                  {imageData.improvedPrompt}
                </div>
              </ScrollArea>
            </div>
          )} */}
        </div>

        {imageData?.src && (
          <ChatBubble_Actions_Image
            fullWidth
            setOpenImage={setOpenImage}
            image_data={image_data}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}
