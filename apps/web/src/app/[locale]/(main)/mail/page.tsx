import type { Metadata } from "next";

import MailsPage from "@/features/mail/components/MailsPage";

export const metadata: Metadata = {
  title: "Mail",
};

export default function Page() {
  return <MailsPage />;
}
