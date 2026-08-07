import SupportTicketCard from "@/features/support/components/SupportTicketCard";
import type { SupportTicketData } from "@/types/features/supportTypes";

export default function SupportTicketSection({
  support_ticket_data,
}: {
  support_ticket_data: SupportTicketData[];
}) {
  const handleTicketSubmitted = () => {
    /* card manages its own submitted state; nothing to act on from the bubble */
  };

  return (
    <div className="mt-3 w-full space-y-3">
      {support_ticket_data.map((ticket) => (
        <SupportTicketCard
          ticketData={ticket}
          onSubmitted={handleTicketSubmitted}
          key={ticket.title}
        />
      ))}
    </div>
  );
}
