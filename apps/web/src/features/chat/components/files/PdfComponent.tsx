import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

import { Document, Page, pdfjs } from "react-pdf";

import Spinner from "@/components/ui/spinner";
import { Pdf02Icon } from "@/icons";

// Define interfaces for component props
interface PdfContainerProps {
  file: File | null;
  chat_bubble?: boolean;
}

interface PdfComponentProps {
  file: File | string; // Allow both File object and string (URL)
  pageNumber?: number;
  width?: number;
}

export function PdfContainer({ file }: PdfContainerProps) {
  return (
    <div
      className={`bg-opacity-70 my-1 flex w-full flex-col items-center justify-center rounded-2xl bg-surface-50 p-2 text-white`}
    >
      {!!file && (
        <div className="pdf_container">
          <PdfComponent file={file} />
        </div>
      )}

      <div className="flex h-[50px] w-full items-center gap-2 px-2">
        <Pdf02Icon color="foreground-400" height="25" width="25" />
        <div className="flex flex-col">
          <span className="w-[270px] overflow-hidden text-small font-[500] text-ellipsis whitespace-nowrap">
            {file?.name}
          </span>
          <span className="text-xs">{file?.type}</span>
        </div>
      </div>
    </div>
  );
}

export function PdfComponent({
  file,
  pageNumber = 1,
  width = 300,
}: PdfComponentProps) {
  pdfjs.GlobalWorkerOptions.workerSrc = new URL(
    "pdfjs-dist/build/pdf.worker.min.mjs",
    import.meta.url,
  ).toString();

  return (
    <Document file={file}>
      <Page loading={<Spinner />} pageNumber={pageNumber} width={width} />
    </Document>
  );
}
