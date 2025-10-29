import ContactListCard from "@/features/mail/components/ContactListCard";
import { ContactData } from "@/types/features/mailTypes";

export default function ContactListSection({
  contacts_data,
}: {
  contacts_data: ContactData[];
}) {
  return (
    <div className="mt-3 w-full">
      <ContactListCard contacts={contacts_data} />
    </div>
  );
}
