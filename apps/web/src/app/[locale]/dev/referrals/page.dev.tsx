import { Suspense } from "react";
import { ReferralsGallery } from "./ReferralsGallery";

export default function ReferralsGalleryPage() {
  return (
    <Suspense>
      <ReferralsGallery />
    </Suspense>
  );
}
