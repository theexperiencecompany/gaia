import SupportTicketCard from "@/features/support/components/SupportTicketCard";
import type { SupportTicketData } from "@/types/features/supportTypes";

export default function SupportTicketSection({
  support_ticket_data,
}: {
  support_ticket_data: SupportTicketData[];
}) {
  const handleTicketSubmitted = () => {
    // Optional: Add any post-submit logic here
    console.log("Support ticket submitted from chat bubble");
  };

  return (
    <div className="mt-3 w-full space-y-3">
      {support_ticket_data.map((ticket, index) => (
        <SupportTicketCard
          ticketData={ticket}
          onSubmitted={handleTicketSubmitted}
          key={index}
        />
      ))}
    </div>
  );
}
