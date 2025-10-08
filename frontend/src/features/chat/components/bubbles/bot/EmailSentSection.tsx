import EmailSentCard from "@/features/mail/components/EmailSentCard";
import { EmailSentData } from "@/types/features/mailTypes";

export default function EmailSentSection({
  email_sent_data,
}: {
  email_sent_data: EmailSentData[];
}) {
  return (
    <div className="mt-3 w-full space-y-3">
      {email_sent_data.map((email, index) => (
        <EmailSentCard emailSentData={email} key={index} />
      ))}
    </div>
  );
}
