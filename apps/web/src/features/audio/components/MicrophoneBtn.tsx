"use client";

// import Lottie from "react-lottie";
// import recordingAnimation from "../lotties/recording.json";
import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { useRef, useState } from "react";

import { Cancel01Icon, Mic02Icon, Tick02Icon } from "@/icons";

// Define props type for the MicrophoneBtn component
interface MicrophoneBtnProps {
  loading: boolean;
  // onTranscriptionComplete: (transcript: string) => void;
}

export default function MicrophoneBtn({
  loading,
}: // onTranscriptionComplete,
MicrophoneBtnProps) {
  const [open, setOpen] = useState<boolean>(false);
  const [_isRecording, _setIsRecording] = useState<boolean>(false);
  const [transcript, _setTranscript] = useState<string>("");
  const _recognitionRef = useRef(null);

  // useEffect(() => {
  //   if (
  //     typeof window !== "undefined" &&
  //     ("SpeechRecognition" in window || "webkitSpeechRecognition" in window)
  //   ) {
  //     const SpeechRecognition =
  //       window.SpeechRecognition || window.webkitSpeechRecognition;

  //     recognitionRef.current = new SpeechRecognition();
  //     recognitionRef.current.continuous = true;
  //     recognitionRef.current.interimResults = true;
  //     recognitionRef.current.lang = "en-US";

  //     recognitionRef.current.onresult = (event: any) => {
  //       let interimTranscript = "";
  //       let finalTranscript = "";

  //       for (let i = event.resultIndex; i < event.results.length; i++) {
  //         const result = event.results[i];
  //         const transcript = result[0].transcript;

  //         if (result.isFinal) {
  //           finalTranscript += transcript + " ";
  //         } else {
  //           interimTranscript += transcript;
  //         }
  //       }

  //       setTranscript(finalTranscript + interimTranscript);
  //     };

  //     recognitionRef.current.onerror = (event: any) => {
  //       console.error("Recognition error:", event.error);
  //       stopRecording(); // Stop recording on error
  //     };

  //     recognitionRef.current.onend = () => {
  //       setIsRecording(false);
  //     };
  //   } else {
  //     console.log("Speech recognition not supported");
  //   }

  //   return () => {
  //     stopRecording(); // Ensure to stop on cleanup
  //   };
  // // }, []);

  // const startRecording = () => {
  //   setTranscript("");
  //   setIsRecording(true);
  //   recognitionRef.current?.start();
  // };

  // const stopRecording = () => {
  //   recognitionRef.current?.stop();
  //   setIsRecording(false);
  // };

  // const handleClose = () => {
  //   stopRecording();
  //   setOpen(false);
  // };

  // const handleSubmit = () => {
  //   stopRecording();
  //   // onTranscriptionComplete(transcript);
  //   setOpen(false);
  // };

  return (
    <>
      <Button
        isIconOnly
        aria-label="Microphone"
        isDisabled={loading}
        radius="full"
        variant="light"
        onPress={() => {
          setOpen(true);
          // startRecording();
        }}
      >
        <Mic02Icon />
      </Button>
      <Modal
        hideCloseButton
        backdrop="opaque"
        classNames={{ base: "w-full max-w-md p-4 dark text-white" }}
        isOpen={open}
        // onClose={handleClose}
        onOpenChange={setOpen}
      >
        <ModalContent>
          <ModalHeader className="flex flex-col items-center">
            {_isRecording ? "Recording Voice" : "Voice Recording Complete"}
          </ModalHeader>
          <ModalBody className="flex flex-col items-center space-y-4">
            {_isRecording && (
              <div className="lottie_container">
                {/* <Lottie
                  options={{
                    loop: true,
                    autoplay: true,
                    animationData: recordingAnimation,
                    rendererSettings: {
                      preserveAspectRatio: "xMidYMid slice",
                    },
                  }}
                  isClickToPauseDisabled={true}
                  height={50}
                  width={100} */}
                {/* /> */}
              </div>
            )}
            <div className="max-h-[200px] min-h-[100px] w-full overflow-y-auto rounded-md bg-surface-800 p-4">
              <p className="whitespace-pre-wrap">{transcript}</p>
            </div>
          </ModalBody>
          <ModalFooter className="flex w-full justify-center space-x-4">
            <Button
              isIconOnly
              color="danger"
              variant="flat"
              // onPress={handleClose}
            >
              <Cancel01Icon color="red" />
            </Button>
            <Button
              isIconOnly
              color="success"
              variant="flat"
              // onPress={handleSubmit}
            >
              <Tick02Icon color="green" />
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  );
}
