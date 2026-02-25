import { ScrollShadow } from "@heroui/scroll-shadow";
import { Call02Icon, Mail01Icon } from "@icons";
import { Gmail } from "@/components";
import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import type { PeopleSearchData } from "@/types/features/mailTypes";

interface PeopleSearchCardProps {
  people: PeopleSearchData[];
}

export default function PeopleSearchCard({ people }: PeopleSearchCardProps) {
  return (
    <CollapsibleListWrapper
      icon={<Gmail width={20} height={20} />}
      count={people.length}
      label="Person/People"
      isCollapsible={true}
    >
      <div className="w-full max-w-2xl rounded-3xl bg-zinc-800 p-3 text-white">
        {/* People List */}
        <ScrollShadow className="max-h-[400px] divide-y divide-zinc-700">
          {people.map((person) => (
            <div
              key={person.email + person.phone}
              className="group flex cursor-default items-start gap-4 p-3 transition-colors hover:bg-zinc-700"
            >
              {/* Name Column */}
              <div className="w-40 flex-shrink-0">
                <span className="block truncate text-sm font-medium text-gray-300">
                  {person.name}
                </span>
              </div>

              {/* Details Column */}
              <div className="min-w-0 flex-1 space-y-1">
                {person.email && (
                  <div className="flex items-center gap-2 text-sm text-gray-400">
                    <Mail01Icon className="h-3.5 w-3.5 flex-shrink-0" />
                    <span className="truncate">{person.email}</span>
                  </div>
                )}
                {person.phone && (
                  <div className="flex items-center gap-2 text-sm text-gray-400">
                    <Call02Icon className="h-3.5 w-3.5 flex-shrink-0" />
                    <span>{person.phone}</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </ScrollShadow>
      </div>
    </CollapsibleListWrapper>
  );
}
