import { Avatar } from "@heroui/avatar";
import { REFERRAL_UI_COPY } from "../referralCopy";
import type { InviteSender } from "../stores/inviteStore";
import type { ReferralSuggestion } from "../types/contract";
import { InviteButton } from "./InviteButton";

interface SuggestionsListProps {
  suggestions: ReferralSuggestion[];
  send: InviteSender;
}

export function SuggestionsList({ suggestions, send }: SuggestionsListProps) {
  if (suggestions.length === 0) return null;
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-medium text-zinc-300">
        {REFERRAL_UI_COPY.suggestionsTitle}
      </h2>
      <ul className="divide-y divide-zinc-800/60 rounded-2xl bg-zinc-900/60">
        {suggestions.map((suggestion) => (
          <li
            key={suggestion.email}
            className="flex items-center gap-3 px-4 py-3"
          >
            <Avatar
              name={suggestion.name ?? suggestion.email}
              size="sm"
              className="shrink-0"
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-zinc-200">
                {suggestion.name ?? suggestion.email}
              </p>
              <p className="truncate text-xs text-zinc-500">
                {REFERRAL_UI_COPY.suggestionReason(
                  suggestion.reason,
                  suggestion.count,
                )}
              </p>
            </div>
            <InviteButton
              email={suggestion.email}
              surface="suggestion"
              send={send}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
