import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import {
  AlertCircleIcon,
  Cancel01Icon,
  File01Icon,
  Loading02Icon,
  PlusSignIcon,
  Upload01Icon,
} from "@icons";
import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { useLoadingText } from "@/features/chat/hooks/useLoadingText";
import { toast } from "@/lib/toast";

import type { UploadedFilePreview } from "./FilePreview";

interface FileUploadProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onFilesUploaded?: (files: UploadedFilePreview[]) => void;
  initialFiles?: File[];
  isPastedFile?: boolean;
}

interface FileWithPreview {
  file: File;
  previewUrl: string | null;
  progress: number;
  error?: string;
}

const MAX_FILE_SIZE = 10 * 1024 * 1024;
const MAX_FILES = 5;
const ALLOWED_FILE_TYPES = [
  "image/jpeg",
  "image/png",
  "image/gif",
  "image/webp",
  "application/pdf",
  "text/plain",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];

export default function FileUpload({
  open,
  onOpenChange,
  onFilesUploaded,
  initialFiles = [],
  isPastedFile = false,
}: FileUploadProps) {
  const { setIsLoading } = useLoading();
  const { setLoadingText, resetLoadingText } = useLoadingText();

  const [files, setFiles] = useState<FileWithPreview[]>([]);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const hasProcessedInitialFiles = useRef(false);

  const validateFile = useCallback((file: File): string | undefined => {
    if (!ALLOWED_FILE_TYPES.includes(file.type)) {
      return "File type not supported";
    }
    if (file.size > MAX_FILE_SIZE) {
      return `File exceeds maximum size of ${MAX_FILE_SIZE / (1024 * 1024)}MB`;
    }
    return undefined;
  }, []);

  useEffect(() => {
    if (open && initialFiles.length > 0 && !hasProcessedInitialFiles.current) {
      if (initialFiles.length + files.length > MAX_FILES) {
        toast.error(`You can upload a maximum of ${MAX_FILES} files at once`);
        return;
      }

      const newFilesWithPreview = initialFiles.map((file) => {
        const error = validateFile(file);
        return {
          file,
          previewUrl: file.type.startsWith("image/")
            ? URL.createObjectURL(file)
            : null,
          progress: 0,
          error,
        };
      });

      setFiles((prev) => [...prev, ...newFilesWithPreview]);
      hasProcessedInitialFiles.current = true;
    } else if (!open) {
      hasProcessedInitialFiles.current = false;
    }
  }, [open, initialFiles, files.length, validateFile]);

  useEffect(() => {
    if (
      open &&
      files.length === 0 &&
      initialFiles.length === 0 &&
      !isPastedFile
    ) {
      setTimeout(() => fileInputRef.current?.click(), 100);
    }
  }, [open, files.length, initialFiles.length, isPastedFile]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(e.target.files || []);
    if (selectedFiles.length === 0) return;

    if (files.length + selectedFiles.length > MAX_FILES) {
      toast.error(`You can upload a maximum of ${MAX_FILES} files at once`);
      return;
    }

    const newFilesWithPreview = selectedFiles.map((file) => {
      const error = validateFile(file);
      return {
        file,
        previewUrl: file.type.startsWith("image/")
          ? URL.createObjectURL(file)
          : null,
        progress: 0,
        error,
      };
    });

    setFiles((prevFiles) => [...prevFiles, ...newFilesWithPreview]);
  };

  const openFileSelector = () => {
    fileInputRef.current?.click();
  };

  const removeFile = (index: number) => {
    setFiles((prevFiles) => {
      const newFiles = [...prevFiles];

      if (newFiles[index].previewUrl) {
        URL.revokeObjectURL(newFiles[index].previewUrl);
      }
      newFiles.splice(index, 1);
      return newFiles;
    });
  };

  const clearAllFiles = () => {
    files.forEach((file) => {
      if (file.previewUrl) URL.revokeObjectURL(file.previewUrl);
    });
    setFiles([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const uploadFiles = async () => {
    if (files.length === 0) return;

    const validFiles = files.filter((f) => !f.error);
    if (validFiles.length === 0) {
      toast.error("No valid files to upload");
      return;
    }
    setLoadingText("Uploading files...");
    setIsLoading(true);
    setIsUploading(true);

    try {
      const tempPreviews: UploadedFilePreview[] = validFiles.map(
        (fileWithPreview, index) => ({
          id: `temp-${index}`,
          url: fileWithPreview.previewUrl || "",
          name: fileWithPreview.file.name,
          type: fileWithPreview.file.type,
          isUploading: true,
        }),
      );

      if (onFilesUploaded) {
        onFilesUploaded(tempPreviews);
      }

      onOpenChange(false);

      const uploadPromises = validFiles.map(async (fileWithPreview, index) => {
        try {
          const response = await chatApi.uploadFile(fileWithPreview.file);

          // Update progress to 100% when done
          setFiles((prevFiles) => {
            const fileIndex = prevFiles.findIndex(
              (f) => f.file === fileWithPreview.file,
            );
            if (fileIndex === -1) return prevFiles;

            const updatedFiles = [...prevFiles];
            updatedFiles[fileIndex] = {
              ...updatedFiles[fileIndex],
              progress: 100,
            };
            return updatedFiles;
          });

          return {
            response,
            fileInfo: fileWithPreview.file,
            tempId: `temp-${index}`,
          };
        } catch (error) {
          console.error(
            `Error uploading file ${fileWithPreview.file.name}:`,
            error,
          );
          throw error;
        }
      });

      const results = await Promise.all(uploadPromises);

      const uploadedFiles: UploadedFilePreview[] = results.map(
        ({ response, fileInfo, tempId }) => ({
          id: response.fileId,
          url: response.url || "",
          name: fileInfo.name,
          type: fileInfo.type,
          description: response.description || `File: ${fileInfo.name}`,
          message: response.message || "File uploaded successfully",
          isUploading: false,
          tempId,
        }),
      );

      if (onFilesUploaded) {
        onFilesUploaded(uploadedFiles);
      }

      clearAllFiles();
    } catch (error) {
      console.error("Error uploading files:", error);
      toast.error("Error uploading files. Please try again.");

      if (onFilesUploaded) {
        onFilesUploaded([]);
      }
    } finally {
      setIsUploading(false);
      setIsLoading(false);
      resetLoadingText();
    }
  };

  const onDragEnter = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const onDragOver = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      if (!isDragging) setIsDragging(true);
    },
    [isDragging],
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);

      const droppedFiles = Array.from(e.dataTransfer.files);
      if (droppedFiles.length === 0) return;

      if (files.length + droppedFiles.length > MAX_FILES) {
        toast.error(`You can upload a maximum of ${MAX_FILES} files at once`);
        return;
      }

      const newFilesWithPreview: FileWithPreview[] = droppedFiles.map(
        (file) => {
          const error = validateFile(file);
          return {
            file,
            previewUrl: file.type.startsWith("image/")
              ? URL.createObjectURL(file)
              : null,
            progress: 0,
            error,
          };
        },
      );

      setFiles((prevFiles) => [...prevFiles, ...newFilesWithPreview]);
    },
    [files.length, validateFile],
  );

  const closeModal = () => {
    clearAllFiles();
    onOpenChange(false);
  };

  return (
    <Modal isOpen={open} onOpenChange={closeModal} backdrop="blur">
      <ModalContent>
        <ModalHeader className="flex flex-col items-center">
          Upload Files{" "}
          {files.length > 0 ? `(${files.length}/${MAX_FILES})` : ""}
        </ModalHeader>
        <ModalBody className="flex flex-col items-center justify-center">
          <input
            type="file"
            ref={fileInputRef}
            className="hidden"
            onChange={handleFileChange}
            accept={ALLOWED_FILE_TYPES.join(",")}
            multiple
          />

          {/* Main upload area */}
          <div
            className={`flex h-64 w-full cursor-pointer flex-col items-center ${files.length > 0 ? "justify-start" : "justify-center"} rounded-xl border-2 border-dashed bg-zinc-950/50 ${
              isDragging
                ? "scale-105 border-primary bg-primary/10"
                : "border-zinc-700 hover:border-primary"
            } p-6 transition-all duration-200 ease-in-out`}
            onClick={openFileSelector}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onDragEnter={onDragEnter}
            onDragLeave={onDragLeave}
          >
            {files.length === 0 ? (
              <>
                <Upload01Icon
                  className={`mb-4 h-10 w-10 ${isDragging ? "text-primary" : "text-zinc-500"}`}
                />
                <p className="mb-2 text-sm font-medium text-white">
                  {isDragging
                    ? "Drop files to upload"
                    : "Click to upload or drag and drop"}
                </p>
                <p className="text-center text-xs text-zinc-500">
                  Images, PDF, TXT, DOC, DOCX (max{" "}
                  {MAX_FILE_SIZE / (1024 * 1024)}MB per file, {MAX_FILES} files
                  max)
                </p>
              </>
            ) : isUploading ? (
              <>
                <Loading02Icon className="mb-4 h-10 w-10 animate-spin text-primary" />
                <p className="mb-2 text-sm font-medium text-white">
                  Uploading files...
                </p>
                <p className="text-xs text-zinc-500">
                  Please wait while your files are being uploaded
                </p>
              </>
            ) : (
              <div className="w-full">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="text-sm font-medium text-white">
                    Selected Files ({files.length}/{MAX_FILES})
                  </h3>
                  <div className="flex gap-2">
                    {files.length < MAX_FILES && (
                      <Button
                        size="sm"
                        variant="flat"
                        onPress={openFileSelector}
                        isDisabled={isUploading}
                        className="flex items-center gap-1"
                      >
                        <PlusSignIcon size={14} />
                        Add More
                      </Button>
                    )}
                    <Button
                      size="sm"
                      color="danger"
                      variant="flat"
                      onPress={clearAllFiles}
                      isDisabled={isUploading}
                    >
                      Clear All
                    </Button>
                  </div>
                </div>

                <div className="max-h-[180px] space-y-2 overflow-x-hidden overflow-y-auto pt-3 pr-2">
                  {files.map((fileWithPreview, index) => (
                    <div
                      key={fileWithPreview.previewUrl}
                      className={`relative flex items-center rounded-xl p-3 ${
                        fileWithPreview.error ? "bg-red-500/10" : "bg-zinc-800"
                      }`}
                    >
                      <Button
                        isIconOnly
                        size="sm"
                        variant="faded"
                        className="absolute top-0 right-0 max-h-7 min-h-7 max-w-7 min-w-7 rounded-full"
                        onPress={() => removeFile(index)}
                        isDisabled={isUploading}
                      >
                        <Cancel01Icon size={14} />
                      </Button>

                      {fileWithPreview.previewUrl ? (
                        <div className="mr-3 h-12 w-12 overflow-hidden rounded-lg">
                          <Image
                            src={fileWithPreview.previewUrl}
                            alt="Preview"
                            width={48}
                            height={48}
                            className="h-full w-full object-cover"
                          />
                        </div>
                      ) : (
                        <div className="mr-3 flex h-12 w-12 items-center justify-center rounded-lg bg-zinc-700">
                          <File01Icon className="h-6 w-6 text-zinc-400" />
                        </div>
                      )}

                      <div className="min-w-0 flex-1">
                        <div className="flex items-center">
                          <p className="max-w-[200px] truncate text-sm font-medium text-white">
                            {fileWithPreview.file.name}
                          </p>
                          {fileWithPreview.error && (
                            <AlertCircleIcon
                              size={14}
                              className="ml-1 shrink-0 text-red-500"
                            />
                          )}
                        </div>

                        {fileWithPreview.error ? (
                          <p className="truncate text-xs text-red-400">
                            {fileWithPreview.error}
                          </p>
                        ) : (
                          <p className="text-xs text-zinc-400">
                            {(fileWithPreview.file.size / 1024 / 1024).toFixed(
                              2,
                            )}{" "}
                            MB
                          </p>
                        )}

                        {isUploading &&
                          fileWithPreview.progress > 0 &&
                          !fileWithPreview.error && (
                            <div className="mt-1 w-full">
                              <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-700">
                                <div
                                  className="h-full bg-primary transition-all duration-300 ease-in-out"
                                  style={{
                                    width: `${fileWithPreview.progress}%`,
                                  }}
                                />
                              </div>
                            </div>
                          )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </ModalBody>
        <ModalFooter className="flex w-full justify-center">
          <Button
            size="md"
            variant="flat"
            onPress={closeModal}
            isDisabled={isUploading}
          >
            Cancel
          </Button>
          {files.length > 0 && files.some((f) => !f.error) && !isUploading && (
            <Button color="primary" size="md" onPress={uploadFiles}>
              Upload{" "}
              {files.filter((f) => !f.error).length > 0
                ? `(${files.filter((f) => !f.error).length})`
                : ""}
            </Button>
          )}
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
