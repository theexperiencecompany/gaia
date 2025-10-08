import { Accordion, AccordionItem } from "@heroui/accordion";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { Mail, Phone } from "lucide-react";
import { useState } from "react";

import { Gmail } from "@/components";
import { ContactData } from "@/types/features/mailTypes";

interface ContactListCardProps {
  contacts: ContactData[];
}

export default function ContactListCard({ contacts }: ContactListCardProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  return (
    <div className="w-full">
      <Accordion
        className="w-full max-w-(--breakpoint-sm) px-0"
        defaultExpandedKeys={["1"]}
      >
        <AccordionItem
          key="1"
          aria-label="Contacts"
          indicator={<></>}
          title={
            <div className="flex items-center gap-2">
              <Gmail width={20} height={20} />
              <div className="h-full w-fit rounded-lg bg-white/10 p-1 px-3 text-sm font-medium transition-all hover:bg-white/20">
                {isExpanded ? "Hide" : "Show"} {contacts.length} Contact
                {contacts.length !== 1 ? "s" : ""}
              </div>
            </div>
          }
          onPress={() => setIsExpanded((prev) => !prev)}
          className="w-screen max-w-(--breakpoint-sm) px-0"
          isCompact
        >
          <div className="w-full max-w-2xl rounded-3xl bg-zinc-800 p-3 text-white">
            {/* Contact List */}
            <ScrollShadow className="max-h-[400px] divide-y divide-zinc-700">
              {contacts.map((contact, index) => (
                <div
                  key={index}
                  className="group flex cursor-default items-start gap-4 p-3 transition-colors hover:bg-zinc-700"
                >
                  {/* Name Column */}
                  <div className="w-40 flex-shrink-0">
                    <span className="block truncate text-sm font-medium text-gray-300">
                      {contact.name}
                    </span>
                  </div>

                  {/* Details Column */}
                  <div className="min-w-0 flex-1 space-y-1">
                    {contact.email && (
                      <div className="flex items-center gap-2 text-sm text-gray-400">
                        <Mail className="h-3.5 w-3.5 flex-shrink-0" />
                        <span className="truncate">{contact.email}</span>
                      </div>
                    )}
                    {contact.phone && (
                      <div className="flex items-center gap-2 text-sm text-gray-400">
                        <Phone className="h-3.5 w-3.5 flex-shrink-0" />
                        <span>{contact.phone}</span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </ScrollShadow>
          </div>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
