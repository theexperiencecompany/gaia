import EmailComposeCard from "@/features/mail/components/EmailComposeCard";
import type { EmailComposeData } from "@/types/features/convoTypes";

export default function EmailComposeSection({
  email_compose_data,
}: {
  email_compose_data: EmailComposeData[];
}) {
  const handleEmailSent = () => {
    /* intentional no-op */
  };

  return (
    <div className="mt-3 w-full space-y-3">
      {email_compose_data.map((email) => (
        <EmailComposeCard
          emailData={email}
          onSent={handleEmailSent}
          key={email.thread_id}
        />
      ))}
    </div>
  );
}
