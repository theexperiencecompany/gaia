import type {
  ReferralCopyVariant,
  ReferralSuggestionReason,
} from "@shared/api/generated";
import type { OfferPrices } from "./utils/offerPrices";

/**
 * Every referral string, one angle per copy variant. Prices always arrive as
 * OfferPrices so a number in here is a bug. Voice: a friend handing over a
 * gift. Never "referral", "reward" or "% off" in what the user reads.
 */
export interface ReferralCopy {
  page: {
    title: string;
    body: (prices: OfferPrices) => string;
  };
  /** What lands in the friend's chat or inbox; the link rides separately. */
  share: {
    text: (prices: OfferPrices) => string;
    emailSubject: string;
  };
  /** One quiet line over the gift; the price sits under it, not in it. */
  postPayment: {
    title: string;
    cta: string;
  };
  landing: {
    title: (referrer: string) => string;
  };
  og: {
    title: (referrer: string) => string;
    subtitle: (prices: OfferPrices) => string;
  };
}

/** "for your first 2 months" / "for their first month". */
const introPeriod = (p: OfferPrices, whose: "your" | "their") =>
  p.cycles === 1
    ? `for ${whose} first month`
    : `for ${whose} first ${p.cycles} months`;

/** "$15/month for their first 2 months": the gift, said to whoever gets it. */
const giftPrice = (p: OfferPrices, whose: "your" | "their") =>
  `${p.intro}/month ${introPeriod(p, whose)}`;

export const REFERRAL_COPY: Record<ReferralCopyVariant, ReferralCopy> = {
  gift: {
    page: {
      title: "Share the joy of GAIA",
      body: (p) =>
        `Your friends get GAIA for just ${giftPrice(p, "their")}. You get a free month every time one subscribes!`,
    },
    share: {
      text: (p) =>
        `I've been using GAIA and it's honestly made my days lighter. Here's GAIA for ${giftPrice(p, "your")} 💛`,
      emailSubject: "A little gift for you: GAIA",
    },
    postPayment: {
      title: "Know someone who'd love GAIA?",
      cta: "Send the gift",
    },
    landing: {
      title: (referrer) => `${referrer} sent you a gift!`,
    },
    og: {
      title: (referrer) => `${referrer} sent you a gift`,
      subtitle: (p) => `GAIA for ${giftPrice(p, "your")}`,
    },
  },
  earn: {
    page: {
      title: "Earn free months of GAIA",
      body: (p) =>
        `Every friend who subscribes gets you a free month, with no limit. They start at just ${p.intro}/month.`,
    },
    share: {
      text: (p) =>
        `GAIA runs my inbox and calendar now. Try it for ${giftPrice(p, "your")}:`,
      emailSubject: "Try GAIA for less",
    },
    postPayment: {
      title: "Your next month could be free",
      cta: "Share your link",
    },
    landing: {
      title: (referrer) => `${referrer} wants you on GAIA`,
    },
    og: {
      title: (referrer) => `${referrer} invited you to GAIA`,
      subtitle: (p) => giftPrice(p, "your"),
    },
  },
  time_back: {
    page: {
      title: "Give a friend their time back",
      body: (p) =>
        `GAIA takes the busywork off your plate. Pass it on: friends pay ${giftPrice(p, "their")}, and you get a free month for each one who subscribes.`,
    },
    share: {
      text: (p) =>
        `GAIA handles my email, calendar and follow-ups so I don't have to. Get it for ${giftPrice(p, "your")}:`,
      emailSubject: "This gave me hours back every week",
    },
    postPayment: {
      title: "Know someone who needs their time back?",
      cta: "Pass it on",
    },
    landing: {
      title: (referrer) => `${referrer} is giving you hours back`,
    },
    og: {
      title: (referrer) => `${referrer} is giving you hours back`,
      subtitle: (p) => `GAIA for ${giftPrice(p, "your")}`,
    },
  },
  insider: {
    page: {
      title: "Bring your people in",
      body: (p) =>
        `Friends of GAIA members get it for ${giftPrice(p, "their")}. You get a free month for each one who subscribes.`,
    },
    share: {
      text: (p) =>
        `I'm letting a few friends into GAIA. You get it for ${giftPrice(p, "your")}:`,
      emailSubject: "You're in: GAIA",
    },
    postPayment: {
      title: "Bring a friend in",
      cta: "Share your link",
    },
    landing: {
      title: (referrer) => `${referrer} saved you a spot`,
    },
    og: {
      title: (referrer) => `${referrer} saved you a spot on GAIA`,
      subtitle: (p) => giftPrice(p, "your"),
    },
  },
};

/** Landing angles the browser picks between (2 to 3 live at once); the pick rides on /resolve. */
export const LIVE_LANDING_VARIANTS: readonly ReferralCopyVariant[] = [
  "gift",
  "earn",
  "time_back",
];

/** A link preview renders before any browser picks a landing angle, so it always speaks gift. */
export const INVITE_OG_VARIANT: ReferralCopyVariant = "gift";

/** The sidebar card reads the same for everyone: the earn angle is the clearest at that size. */
export const REFERRAL_SIDEBAR_COPY = {
  title: "Your next month, free",
  body: (p: OfferPrices) =>
    `Friends get GAIA for ${p.intro}/month. You get a free month.`,
  cta: "Share your link",
} as const;

/** Strings that read the same in every angle. */
export const REFERRAL_UI_COPY = {
  share: "Share",
  copyLink: "Copy link",
  copied: "Copied",
  qrCode: "QR code",
  qrHint: "Scan to open your link on a phone",
  qrHintShort: "Scan to share",
  perMonth: "/month",
  /** The one line under a gift price, "for their first 2 months". */
  giftPeriod: (p: OfferPrices) => introPeriod(p, "their"),
  giftLine: (p: OfferPrices) => giftPrice(p, "their"),
  monthsEarned: (n: number) =>
    n === 1 ? "1 free month earned" : `${n} free months earned`,
  toNextMilestone: (left: number, milestone: number) =>
    `${left} more to reach ${milestone} friends`,
  onTheWay: (n: number) =>
    n === 1 ? "1 friend on the way" : `${n} friends on the way`,
  nextBill: (date: string) => `Next bill moves to ${date}`,
  friendsTitle: "Friends",
  unnamedFriend: "A friend",
  friendsEmpty:
    "Your first friend who subscribes gets you a free month. Who's it going to be?",
  joinedOn: (date: string) => `Joined ${date}`,
  subscribedOn: (date: string) => `Subscribed ${date}`,
  statusPaid: "Free month",
  statusPending: "On the way",
  pendingHint: "You get a free month when they subscribe",
  suggestionsTitle: "People you might invite",
  suggestionReason: (reason: ReferralSuggestionReason, count: number) =>
    reason === "met"
      ? `You've met ${count} times lately`
      : `You've emailed ${count} times lately`,
  invite: "Invite",
  inviteToGaia: "Invite to GAIA",
  sent: "Sent",
  undo: "Undo",
  invited: "Invited",
  cannotInvite: "Can't invite",
  optedOut: "Opted out",
  maybeLater: "Maybe later",
  landingCta: "Claim your gift",
  /** "for your first 2 months", after the struck-through and gift prices. */
  landingPeriod: (p: OfferPrices) => introPeriod(p, "your"),
  landingPrice: (p: OfferPrices) => giftPrice(p, "your"),
  thenRegular: (p: OfferPrices) => `then ${p.regular}/month`,
  landingFrom: (referrer: string) => `From ${referrer}`,
  subscribeFirstTitle: "Gifts come with GAIA Pro",
  subscribeFirstBody:
    "Subscribe and you'll get a link that gives friends GAIA for less, plus a free month for you every time one joins.",
  subscribeFirstCta: "See plans",
  loadFailedTitle: "Couldn't load your invite link",
  tryAgain: "Try again",
  ogTicketLabel: "A GIFT FOR YOU",
  ogDomain: "heygaia.io",
  landingFallbackTitle: "Meet GAIA",
  landingFallbackCta: "Get started",
} as const;

export const CHANNEL_LABELS = {
  whatsapp: "WhatsApp",
  sms: "Messages",
  x: "X",
  linkedin: "LinkedIn",
  email: "Email",
} as const;
