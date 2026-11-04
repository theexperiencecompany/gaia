import { Suspense } from "react";
import { ApproveDeviceForm } from "@/features/devices/components/ApproveDeviceForm";

export default function ApproveDevicePage() {
  return (
    <div className="mx-auto flex w-full max-w-lg flex-col px-6 py-16">
      <Suspense fallback={null}>
        <ApproveDeviceForm />
      </Suspense>
    </div>
  );
}
