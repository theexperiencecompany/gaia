import PeopleSearchCard from "@/features/mail/components/PeopleSearchCard";
import type { PeopleSearchData } from "@/types/features/mailTypes";

export default function PeopleSearchSection({
  people_search_data,
}: {
  people_search_data: PeopleSearchData[];
}) {
  return (
    <div className="mt-3 w-full">
      <PeopleSearchCard people={people_search_data} />
    </div>
  );
}
