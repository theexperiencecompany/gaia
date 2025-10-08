import { Card, CardBody } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { Mail, Phone, User } from "lucide-react";

import { Gmail } from "@/components";
import { ContactData } from "@/types/features/mailTypes";

interface ContactListCardProps {
  contacts: ContactData[];
}

export default function ContactListCard({ contacts }: ContactListCardProps) {
  return (
    <Card className="mx-auto my-3 w-full max-w-2xl bg-zinc-800 text-white">
      <CardBody className="p-4">
        {/* Header */}
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Gmail width={20} height={20} />
            <User className="h-5 w-5" />
            <span className="text-sm font-medium">Contacts</span>
          </div>
          <Chip size="sm" variant="flat" color="primary" className="text-xs">
            {contacts.length} {contacts.length === 1 ? "contact" : "contacts"}
          </Chip>
        </div>

        {/* Contact List */}
        <ScrollShadow className="max-h-96 overflow-y-auto">
          <div className="space-y-2">
            {contacts.map((contact, index) => (
              <div
                key={index}
                className="rounded-lg border border-zinc-700 bg-zinc-900/50 p-3 transition-colors hover:bg-zinc-900"
              >
                <div className="flex flex-col gap-2">
                  {/* Name */}
                  <div className="font-medium text-gray-200">
                    {contact.name}
                  </div>

                  {/* Email */}
                  {contact.email && (
                    <div className="flex items-center gap-2 text-sm text-gray-400">
                      <Mail className="h-4 w-4" />
                      <span className="break-all">{contact.email}</span>
                    </div>
                  )}

                  {/* Phone */}
                  {contact.phone && (
                    <div className="flex items-center gap-2 text-sm text-gray-400">
                      <Phone className="h-4 w-4" />
                      <span>{contact.phone}</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </ScrollShadow>
      </CardBody>
    </Card>
  );
}
