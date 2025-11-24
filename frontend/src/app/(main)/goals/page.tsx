import type { Metadata } from "next";

import GoalsPage from "@/features/goals/components/GoalsPage";

export const metadata: Metadata = {
  title: "goals",
};

export default function Page() {
  return <GoalsPage />;
}
