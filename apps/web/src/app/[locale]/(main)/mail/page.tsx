import "./page.css";
import "./page.2.css";
import "./page.3.css";
import "./page.4.css";
import "./page.5.css";
import type { Metadata } from "next";

import MailsPage from "@/features/mail/components/MailsPage";

export const metadata: Metadata = {
  title: "Mail",
};

export default function Page() {
  return <MailsPage />;
}
