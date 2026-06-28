import SuspenseLoader from "@/components/shared/SuspenseLoader";

export default function Loading() {
  return (
    <div className="flex min-h-[60vh] w-full items-center justify-center">
      <SuspenseLoader />
    </div>
  );
}
