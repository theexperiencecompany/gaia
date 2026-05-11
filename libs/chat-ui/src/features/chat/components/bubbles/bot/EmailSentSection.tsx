import EmailSentCard from "@/features/mail/components/EmailSentCard";
import type { EmailSentData } from "@/types/features/mailTypes";

export default function EmailSentSection({
  email_sent_data,
}: {
  email_sent_data: EmailSentData[];
}) {
  return (
    <div className="mt-3 w-full space-y-3">
      {email_sent_data.map((email) => (
        <EmailSentCard emailSentData={email} key={email.message_id} />
      ))}
    </div>
  );
}
