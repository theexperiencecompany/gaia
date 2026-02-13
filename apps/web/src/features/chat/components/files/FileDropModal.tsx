"use client";

import { AnimatePresence, m } from "motion/react";

import { File01Icon, FileUploadIcon, Upload01Icon } from "@/icons";

interface FileDropModalProps {
  isDragging: boolean;
  acceptedFileTypes?: string[];
  maxFileSize?: number;
}

export function FileDropModal({
  isDragging,
  acceptedFileTypes = ["*"],
  maxFileSize = 10,
}: FileDropModalProps) {
  return (
    <AnimatePresence>
      {isDragging && (
        <m.div
          className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <m.div
            className="w-full max-w-md rounded-2xl border-2 border-dashed border-primary/70 bg-linear-to-b from-[#092a36] to-black p-8 shadow-2xl"
            initial={{ scale: 0.9, y: 10 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.9, y: 10 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
          >
            <div className="flex flex-col items-center text-center">
              <m.div
                className="mb-5 flex h-20 w-20 items-center justify-center rounded-full bg-primary/10 text-primary"
                animate={{
                  y: [0, -10, 0],
                  scale: [1, 1.05, 1],
                }}
                transition={{
                  repeat: Number.POSITIVE_INFINITY,
                  duration: 2,
                  ease: "easeInOut",
                }}
              >
                <Upload01Icon size={36} strokeWidth={1.5} />
              </m.div>

              <h3 className="mb-2 text-2xl font-bold text-foreground">
                Drop files here
              </h3>

              <p className="text-muted-foreground mb-4">
                Release to upload your files
              </p>

              <div className="text-muted-foreground mt-2 flex flex-wrap items-center justify-center gap-2 text-xs">
                <div className="flex items-center rounded-full bg-zinc-800 px-3 py-1">
                  <FileUploadIcon size={12} className="mr-1" />
                  <span>Max {maxFileSize}MB</span>
                </div>

                <div className="flex items-center rounded-full bg-zinc-800 px-3 py-1">
                  <File01Icon size={12} className="mr-1" />
                  <span>
                    {acceptedFileTypes.includes("*")
                      ? "All file types"
                      : acceptedFileTypes.join(", ")}
                  </span>
                </div>
              </div>
            </div>
          </m.div>
        </m.div>
      )}
    </AnimatePresence>
  );
}
