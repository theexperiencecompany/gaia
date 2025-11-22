import { Button } from "@heroui/button";
// import Spinner from "@/components/ui/spinner";
import * as React from "react";

import { Watch02Icon } from '@/icons';
import { VolumeHighIcon, VolumeOffIcon } from "@/icons";
import { api } from "@/lib/api";

export default function TextToSpeech({ text }: { text: string }) {
  const [loading, setLoading] = React.useState(false);
  const [isPlaying, setIsPlaying] = React.useState(false);
  const [audio, setAudio] = React.useState<HTMLAudioElement | null>(null);

  const handleTextToSpeech = async () => {
    try {
      if (isPlaying || loading) {
        if (audio) {
          audio.pause();
          audio.src = "";
        }
        setAudio(null);
        setIsPlaying(false);
        setLoading(false);
      } else {
        setLoading(true);

        // API Call
        const response = await api.post(
          "/synthesize",
          { text },
          { responseType: "arraybuffer" },
        );

        // Convert audio data to a Blob
        const audioBlob = new Blob([response.data], { type: "audio/wav" });
        const audioUrl = URL.createObjectURL(audioBlob);

        // Create and play the audio
        const newAudio = new Audio(audioUrl);

        await newAudio.play();
        setAudio(newAudio);

        setIsPlaying(true);
        newAudio.onended = () => setIsPlaying(false);
      }
    } catch (error) {
      console.error("Error synthesizing speech:", error);
    } finally {
      setLoading(false);
    }
  };

  // Cleanup audio when component unmounts
  React.useEffect(() => {
    return () => {
      if (audio) {
        audio.pause();
        audio.src = "";
      }
    };
  }, [audio]);

  return (
    <Button
      isIconOnly
      className="h-fit w-fit rounded-md p-0"
      disabled={loading || isPlaying}
      size="sm"
      style={{ minWidth: "22px" }}
      variant="light"
      onPress={handleTextToSpeech}
    >
      {loading ? (
        <Watch02Icon className="animate-spin text-[24px] text-[#9b9b9b]" />
      ) : isPlaying ? (
        <VolumeOffIcon className="text-[18px] text-[#9b9b9b]" />
      ) : (
        <VolumeHighIcon />
      )}
    </Button>
  );
}
