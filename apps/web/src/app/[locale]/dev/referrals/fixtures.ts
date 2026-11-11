import type {
  ReferralCopyVariant,
  ReferralLayoutVariant,
  ReferralMeResponse,
  ReferralOffer,
  ReferralResolveResponse,
  ReferralSuggestion,
  ReferralWeeklyCardResponse,
  ReferredFriend,
  URLResponse,
} from "@shared/api/generated";
import type { UserInfo } from "@/features/auth/api/authApi";
import type {
  InvitePhase,
  InviteSender,
} from "@/features/referrals/stores/inviteStore";

export const FIXTURE_OFFER: ReferralOffer = {
  currency: "USD",
  monthly_regular_minor: 3000,
  monthly_intro_minor: 1500,
  intro_cycles: 2,
  yearly_regular_minor: 30000,
  yearly_discount_minor: 3000,
};

/** In the order a referrer meets them, then what their friend sees. */
export const GALLERY_VIEWS = [
  "onboarding",
  "page",
  "settings",
  "nudges",
  "weekly",
  "og",
  "landing",
] as const;
export type GalleryView = (typeof GALLERY_VIEWS)[number];

export const COPY_VARIANTS: readonly ReferralCopyVariant[] = [
  "gift",
  "earn",
  "time_back",
];
export const LAYOUT_VARIANTS: readonly ReferralLayoutVariant[] = [
  "ticket",
  "progress",
  "minimal",
];

export const GALLERY_STATES = ["empty", "mid", "many"] as const;
export type GalleryState = (typeof GALLERY_STATES)[number];

const FIRST_NAMES = [
  "Priya",
  "Marcus",
  "Lena",
  "Diego",
  "Aiko",
  "Tomás",
  "Ngozi",
  "Sam",
  "Ingrid",
  "Ravi",
  "Chloé",
  "Kwame",
  "Mei",
  "Oscar",
  "Hana",
  "Yusuf",
  "Elif",
  "Jonah",
  "Sofia",
  "Arjun",
  "Maya",
  "Felix",
];

const friend = (index: number, paid: boolean): ReferredFriend => {
  const joined = new Date(Date.UTC(2026, 9, 12 - index * 3));
  return {
    first_name: FIRST_NAMES[index % FIRST_NAMES.length],
    status: paid ? "paid" : "joined",
    joined_at: joined.toISOString(),
    paid_at: paid
      ? new Date(joined.getTime() + 2 * 24 * 60 * 60 * 1000).toISOString()
      : null,
  };
};

const base = {
  code: "aryan-k7f2",
  share_link: "https://heygaia.io/invite/aryan-k7f2",
  offer: FIXTURE_OFFER,
  copy_variant: "gift",
  layout_variant: "ticket",
} as const;

export const FIXTURE_ME: Record<GalleryState, ReferralMeResponse> = {
  empty: {
    ...base,
    months_earned: 0,
    months_applied: 0,
    months_banked: 0,
    next_billing_date: "2026-11-02T00:00:00Z",
    friends: [],
  },
  mid: {
    ...base,
    months_earned: 3,
    months_applied: 3,
    months_banked: 0,
    next_billing_date: "2027-02-02T00:00:00Z",
    friends: [0, 1, 2, 3, 4].map((i) => friend(i, i < 3)),
  },
  many: {
    ...base,
    months_earned: 14,
    months_applied: 14,
    months_banked: 0,
    next_billing_date: "2028-01-02T00:00:00Z",
    friends: FIRST_NAMES.map((_, i) => friend(i, i % 3 !== 2)),
  },
};

const week = (
  actions: number,
  workflowRuns: number,
  minutesSaved: number,
): ReferralWeeklyCardResponse => ({
  show: true,
  stats: {
    window_start: "2026-10-12T00:00:00Z",
    window_end: "2026-10-19T00:00:00Z",
    actions,
    workflow_runs: workflowRuns,
    minutes_saved: minutesSaved,
  },
  code: base.code,
  share_link: base.share_link,
  copy_variant: base.copy_variant,
});

/** Numbers are the API's own arithmetic: 2 minutes an action, 10 a workflow run. */
export const FIXTURE_WEEKLY: Record<GalleryState, ReferralWeeklyCardResponse> =
  {
    empty: week(9, 0, 18),
    mid: week(84, 6, 228),
    many: week(310, 41, 1030),
  };

export const FIXTURE_SUGGESTIONS: ReferralSuggestion[] = [
  { name: "Jordan Lee", email: "jordan@northwind.co", reason: "met", count: 6 },
  {
    name: "Ana Ruiz",
    email: "ana.ruiz@gmail.com",
    reason: "emailed",
    count: 11,
  },
  { name: null, email: "dev@pollinate.studio", reason: "emailed", count: 4 },
];

export const FIXTURE_RESOLVE: Record<
  "valid" | "photo" | "invalid",
  ReferralResolveResponse
> = {
  valid: {
    valid: true,
    referrer_first_name: "Aryan",
    referrer_picture: null,
    offer: FIXTURE_OFFER,
  },
  photo: {
    valid: true,
    referrer_first_name: "Aryan",
    referrer_picture: "https://avatars.githubusercontent.com/u/1?v=4",
    offer: FIXTURE_OFFER,
  },
  invalid: {
    valid: false,
    referrer_first_name: null,
    referrer_picture: null,
    offer: FIXTURE_OFFER,
  },
};

/** Every gallery invite lands as sent, except the one address that already got one. */
export const ALREADY_INVITED_EMAIL = "ana.ruiz@gmail.com";

export const fixtureSender: InviteSender = async (email) => {
  await new Promise((resolve) => setTimeout(resolve, 400));
  return email === ALREADY_INVITED_EMAIL ? "already_invited" : "sent";
};

/** The signed-in gallery user, as GET /user/me returns them. */
export const fixtureUser = (sentWithGaia: boolean): UserInfo => ({
  message: "ok",
  auth_provider: "workos",
  user_id: "6650f0c2a1b2c3d4e5f60718",
  name: "Aryan K",
  email: "aryan@heygaia.io",
  picture: null,
  onboarding: {
    completed: true,
    completed_at: "2026-10-01T09:00:00Z",
    first_message_conversation_id: null,
    phase: null,
    preferences: { sent_with_gaia: sentWithGaia },
  },
});

/** One friend at each stage the API reports, plus the one with no first name. */
export const FIXTURE_FRIEND_STATES: Record<
  "pending" | "earned" | "unnamed",
  ReferredFriend
> = {
  pending: {
    first_name: "Priya",
    status: "joined",
    joined_at: "2026-10-28T00:00:00Z",
    paid_at: null,
  },
  earned: {
    first_name: "Marcus",
    status: "paid",
    joined_at: "2026-10-12T00:00:00Z",
    paid_at: "2026-10-14T00:00:00Z",
  },
  unnamed: {
    first_name: null,
    status: "joined",
    joined_at: "2026-11-02T00:00:00Z",
    paid_at: null,
  },
};

/** A suggestion per settled invite label, held in the invite store as that phase. */
export const FIXTURE_SUGGESTION_PHASES: {
  suggestion: ReferralSuggestion;
  phase: InvitePhase;
}[] = [
  {
    suggestion: {
      name: "Hana Sato",
      email: "hana@sato.design",
      reason: "met",
      count: 3,
    },
    phase: { phase: "held" },
  },
  {
    suggestion: {
      name: "Felix Brandt",
      email: "felix@brandt.dev",
      reason: "emailed",
      count: 8,
    },
    phase: { phase: "done", status: "sent" },
  },
  {
    suggestion: {
      name: "Elif Kaya",
      email: "elif@kaya.io",
      reason: "emailed",
      count: 2,
    },
    phase: { phase: "done", status: "invalid" },
  },
  {
    suggestion: {
      name: "Jonah Weiss",
      email: "jonah@weiss.fm",
      reason: "met",
      count: 1,
    },
    phase: { phase: "done", status: "unsubscribed" },
  },
];

/** People whose address GAIA wrote into a reply, one per hover-card invite state. */
export const FIXTURE_CONTACTS: {
  label: string;
  metadata: URLResponse;
  phase: InvitePhase | null;
}[] = [
  {
    label: "Not invited yet",
    metadata: { url: "maya@lumen.studio", title: "Maya Chen" },
    phase: null,
  },
  {
    label: "Sent, inside the undo window",
    metadata: { url: "oscar@fjord.no", title: "Oscar Lund" },
    phase: { phase: "held" },
  },
  {
    label: "Sent",
    metadata: { url: "sofia@arcade.co", title: "Sofia Marin" },
    phase: { phase: "done", status: "sent" },
  },
  {
    label: "Already invited",
    metadata: { url: "ravi@kiln.app", title: null },
    phase: { phase: "done", status: "already_invited" },
  },
];
