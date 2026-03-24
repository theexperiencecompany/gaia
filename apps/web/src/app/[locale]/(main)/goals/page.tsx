// Goals feature is temporarily disabled. Re-enable by reverting this file.
// import type { Metadata } from "next";
// import GoalsPage from "@/features/goals/components/GoalsPage";
// export const metadata: Metadata = { title: "goals" };
// export default function Page() { return <GoalsPage />; }

import { notFound } from "next/navigation";

export default function Page() {
  notFound();
}
