import "./page.css";
import "./page.2.css";
import "./page.3.css";
import "./page.4.css";
import "./page.5.css";
// Calendar feature is temporarily disabled. Re-enable by reverting this file.
// import CalendarPage from "@/features/calendar/components/CalendarPage";
// export default function Page() { return <CalendarPage />; }

import { notFound } from "next/navigation";

export default function Page() {
  notFound();
}
