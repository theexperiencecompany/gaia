// @vitest-environment jsdom
/**
 * Pins every price, currency, discount and plan label the web shows today.
 *
 * Written before the money single-source refactor and kept unchanged through
 * it: each surface renders from the live catalogue (GET /payments/plans,
 * 2026-10-08) and the snapshots are the text a user reads. A refactor that
 * moves where a number comes from must leave every one of them identical.
 */
import { act, cleanup, render } from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import type {
  Plan,
  UserSubscriptionStatus,
} from "@/features/pricing/api/pricingApi";

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: {
    SUBSCRIPTION_PLAN_VIEWED: "subscription:plan_viewed",
    PRICING_PLAN_SELECTED: "pricing:plan_selected",
    NAVIGATION_SIDEBAR_CLICKED: "navigation:sidebar_clicked",
  },
  trackEvent: vi.fn(),
}));

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ userId: undefined, name: "" }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("next/image", () => ({
  default: () => null,
}));

vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/c",
}));

vi.mock("@/features/notification/hooks/useNotifications", () => ({
  useNotifications: () => ({ notifications: [] }),
}));

vi.mock("@/features/pricing/hooks/useDodoPayments", () => ({
  useDodoPayments: () => ({
    createSubscriptionAndRedirect: vi.fn(),
    isLoading: false,
    error: null,
  }),
}));

// Carries no money; its confirmation dialog needs a React newer than the test runtime's.
vi.mock("@/features/settings/components/CancelSubscriptionAction", () => ({
  CancelSubscriptionAction: () => null,
}));

const paidState = { isPaid: false, isUnknown: false, hasEverSubscribed: false };

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => paidState,
}));

let mockPlans: Plan[] = [];
let mockPlansLoading = false;
let mockStatus: UserSubscriptionStatus | undefined;

vi.mock("@/features/pricing/hooks/usePricing", () => ({
  usePricing: () => ({
    plans: mockPlans,
    plansLoading: mockPlansLoading,
    isLoading: false,
    error: null,
    subscriptionStatus: mockStatus,
  }),
  useIsSubscriptionStatusUnknown: () => false,
  useUserSubscriptionStatus: () => ({ data: mockStatus, refetch: vi.fn() }),
}));

// Imported after the mocks above so the components pick up the mocked hooks.
import SidebarTopButtons from "@/components/layout/sidebar/SidebarTopButtons";
import { isOfferLive } from "@/config/offer";
import { LetterOffer } from "@/features/chat/components/interface/founder-letter/LetterOffer";
import { BillingPeriodTabs } from "@/features/pricing/components/BillingPeriodTabs";
import { PostPaymentReceipt } from "@/features/pricing/components/PostPaymentReceipt";
import { PricingCards } from "@/features/pricing/components/PricingCards";
import { ProDailyPriceHeading } from "@/features/pricing/components/ProDailyPriceHeading";
import { DiscountBanner } from "@/features/pricing/components/UpgradeModal";
import { buildReceiptDetails } from "@/features/pricing/utils/receiptDetails";
import { SubscriptionSettings } from "@/features/settings/components/SubscriptionSettings";
import { faqData } from "@/lib/faq";
import { pricingFAQs } from "@/lib/page-faqs";
import { generateProductSchema } from "@/lib/seo";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

/** A catalogue row as the API serves it, with the tier it is tagged with. */
type CatalogueRow = Plan & { plan_type: "free" | "pro" | "enterprise" };

const PRO_FEATURES = [
  "Chat on iMessage, WhatsApp, Telegram, Slack and Discord",
  "Inbox triage and drafted replies every morning",
  "Meeting briefs and reminders from your calendar",
  "Todos GAIA works on, not just tracks",
  "Workflows that run without you",
  "Long jobs it keeps working on while you are away",
  "Remembers what you tell it, once",
  "Priority support",
];

function row(fields: CatalogueRow): Plan {
  return fields;
}

const ENTERPRISE = row({
  id: "6a158f054e866965fdac9ddd",
  dodo_product_id: "",
  name: "Enterprise",
  description: "For teams ready to roll GAIA out to every employee.",
  amount: 0,
  currency: "USD",
  duration: "monthly",
  max_users: 0,
  features: [
    "Everything in Pro",
    "SSO, SCIM & audit logs",
    "Custom integrations",
    "Self-host or private cloud",
    "Private Slack support",
    "Dedicated engineer & SLA",
  ],
  is_active: true,
  created_at: "2026-05-26T12:16:05.149000Z",
  updated_at: "2026-08-12T08:29:24.299000Z",
  plan_type: "enterprise",
});

const PRO_MONTHLY = row({
  id: "691d8f37091c87af56990f65",
  dodo_product_id: "pdt_0GMI0BaEpiWey31lpRzxP",
  name: "Pro",
  description: "Everything GAIA does, in one plan.",
  amount: 3000,
  currency: "USD",
  duration: "monthly",
  max_users: 1,
  features: PRO_FEATURES,
  is_active: true,
  created_at: "2025-11-19T09:34:47.803000Z",
  updated_at: "2026-09-17T20:22:17.782000Z",
  plan_type: "pro",
});

const PRO_YEARLY = row({
  ...PRO_MONTHLY,
  id: "691d8f38091c87af56990f66",
  dodo_product_id: "pdt_CXle39shXSw1YoinLaFZW",
  amount: 30000,
  duration: "yearly",
  plan_type: "pro",
});

const LIVE_CATALOGUE = [ENTERPRISE, PRO_MONTHLY, PRO_YEARLY];

const FOUNDER_OFFER = { discountCode: "THANKYOU40", discountPercent: 40 };

/** A subscription row as Dodo localised it: ZAR, while the catalogue is USD. */
const ZAR_SUBSCRIPTION = {
  id: "sub_row_1",
  dodo_subscription_id: "sub_zar",
  user_id: "user_1",
  product_id: PRO_MONTHLY.dodo_product_id,
  status: "active",
  quantity: 1,
  currency: "ZAR",
  payment_frequency_interval: "Month",
  recurring_pre_tax_amount: 57284,
  cancel_at_next_billing_date: false,
  next_billing_date: "2026-11-01T00:00:00Z",
  previous_billing_date: "2026-10-01T00:00:00Z",
  cancelled_at: null,
  last_event_at: null,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

function subscribed(
  currentPlan: Plan | null,
  subscription: Partial<typeof ZAR_SUBSCRIPTION> = {},
): UserSubscriptionStatus {
  return {
    user_id: "user_1",
    current_plan: currentPlan,
    subscription: { ...ZAR_SUBSCRIPTION, ...subscription },
    is_subscribed: true,
    days_remaining: null,
    can_upgrade: true,
    can_downgrade: true,
    has_ever_subscribed: true,
    has_subscription: true,
    plan_type: "pro",
    status: "active",
  };
}

/** HeroUI's Skeleton base class: what a loading price renders instead of a figure. */
const SKELETON = ".bg-content3";

/** What a reader sees: the rendered text, minus injected styles, whitespace collapsed. */
function visibleText(container: HTMLElement): string {
  const copy = container.cloneNode(true) as HTMLElement;
  for (const style of copy.querySelectorAll("style")) style.remove();
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

beforeAll(() => {
  // TextMorph reads matchMedia and getAnimations; jsdom implements neither.
  window.matchMedia =
    window.matchMedia ||
    ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  if (!Element.prototype.getAnimations) {
    Element.prototype.getAnimations = () => [];
  }
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-08T12:00:00Z"));
  mockPlans = LIVE_CATALOGUE;
  mockPlansLoading = false;
  mockStatus = undefined;
  Object.assign(paidState, {
    isPaid: false,
    isUnknown: false,
    hasEverSubscribed: false,
  });
});

afterEach(() => {
  cleanup();
  act(() => {
    useUpgradeModalStore.setState({ open: false, offer: null });
  });
  vi.useRealTimers();
});

describe("pricing cards", () => {
  it("monthly", () => {
    const { container } = render(<PricingCards durationIsMonth />);
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"GAIAEverything GAIA does, in one plan.$30/ monthBilled monthlySubscribeIncludes:Chat on Inbox triage and drafted replies every morningMeeting briefs and reminders from your calendarTodos GAIA works on, not just tracksWorkflows that run without youLong jobs it keeps working on while you are awayRemembers what you tell it, oncePriority supportEnterpriseFor teams ready to roll GAIA out to every employee.CustomPriced around your teamTalk to the teamIncludes:Everything in ProSSO, SCIM & audit logsCustom integrationsSelf-host or private cloudPrivate Slack supportDedicated engineer & SLA"`,
    );
  });

  it("yearly", () => {
    const { container } = render(<PricingCards />);
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"GAIAEverything GAIA does, in one plan.$25/ monthBilled yearly$3002 months freeSubscribeIncludes:Chat on Inbox triage and drafted replies every morningMeeting briefs and reminders from your calendarTodos GAIA works on, not just tracksWorkflows that run without youLong jobs it keeps working on while you are awayRemembers what you tell it, oncePriority supportEnterpriseFor teams ready to roll GAIA out to every employee.CustomPriced around your teamTalk to the teamIncludes:Everything in ProSSO, SCIM & audit logsCustom integrationsSelf-host or private cloudPrivate Slack supportDedicated engineer & SLA"`,
    );
  });

  it("monthly with the founder's offer applied", () => {
    act(() => {
      useUpgradeModalStore.setState({ offer: FOUNDER_OFFER });
    });
    const { container } = render(<PricingCards durationIsMonth />);
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"GAIAEverything GAIA does, in one plan.$30$18/ monthBilled monthlySubscribeIncludes:Chat on Inbox triage and drafted replies every morningMeeting briefs and reminders from your calendarTodos GAIA works on, not just tracksWorkflows that run without youLong jobs it keeps working on while you are awayRemembers what you tell it, oncePriority supportEnterpriseFor teams ready to roll GAIA out to every employee.CustomPriced around your teamTalk to the teamIncludes:Everything in ProSSO, SCIM & audit logsCustom integrationsSelf-host or private cloudPrivate Slack supportDedicated engineer & SLA"`,
    );
  });

  it("yearly with the founder's offer applied", () => {
    act(() => {
      useUpgradeModalStore.setState({ offer: FOUNDER_OFFER });
    });
    const { container } = render(<PricingCards />);
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"GAIAEverything GAIA does, in one plan.$25$15/ monthBilled yearly$300$18026 months freeSubscribeIncludes:Chat on Inbox triage and drafted replies every morningMeeting briefs and reminders from your calendarTodos GAIA works on, not just tracksWorkflows that run without youLong jobs it keeps working on while you are awayRemembers what you tell it, oncePriority supportEnterpriseFor teams ready to roll GAIA out to every employee.CustomPriced around your teamTalk to the teamIncludes:Everything in ProSSO, SCIM & audit logsCustom integrationsSelf-host or private cloudPrivate Slack supportDedicated engineer & SLA"`,
    );
  });

  it("billing period tabs", () => {
    const { container } = render(
      <BillingPeriodTabs isYearly={false} onChange={vi.fn()} />,
    );
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"MonthlyYearly2 months free"`,
    );
  });

  it("never rounds a part month up into the chip", () => {
    // $271/yr saves $89: 2.97 months of $30, so two months free, not three.
    mockPlans = [PRO_MONTHLY, { ...PRO_YEARLY, amount: 27100 }];
    const { container } = render(
      <BillingPeriodTabs isYearly={false} onChange={vi.fn()} />,
    );
    expect(visibleText(container)).toBe("MonthlyYearly2 months free");
  });

  it("discount banners", () => {
    const withPercent = render(<DiscountBanner {...FOUNDER_OFFER} />);
    expect(visibleText(withPercent.container)).toMatchInlineSnapshot(
      `"40% off is applied with THANKYOU40. The prices below are yours."`,
    );
    const codeOnly = render(
      <DiscountBanner discountCode="THANKYOU40" discountPercent={null} />,
    );
    expect(visibleText(codeOnly.container)).toMatchInlineSnapshot(
      `"Use code THANKYOU40 at checkout."`,
    );
  });
});

describe("sidebar promo", () => {
  it("quotes the monthly catalogue price to a never-subscribed user", () => {
    const { container } = render(<SidebarTopButtons />);
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"GAIA is paid onlyGAIA is paid only right now. $30 a month gets you all of it.SubscribeHomeTasksIntegrationsWorkflowsChats"`,
    );
  });

  it("quotes the monthly catalogue price to a lapsed subscriber", () => {
    paidState.hasEverSubscribed = true;
    const { container } = render(<SidebarTopButtons />);
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"Your subscription endedResubscribe for $30 a month to pick up where you left offResubscribeHomeTasksIntegrationsWorkflowsChats"`,
    );
  });

  it("holds the price as a skeleton while the catalogue loads", () => {
    mockPlans = [];
    mockPlansLoading = true;
    const { container } = render(<SidebarTopButtons />);
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"GAIA is paid onlySubscribeHomeTasksIntegrationsWorkflowsChats"`,
    );
    expect(container.querySelector(SKELETON)).not.toBeNull();
  });

  it("names no price when the catalogue could not be read", () => {
    mockPlans = [];
    const { container } = render(<SidebarTopButtons />);
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"GAIA is paid onlySubscribeHomeTasksIntegrationsWorkflowsChats"`,
    );
    expect(container.querySelector(SKELETON)).toBeNull();
  });
});

describe("per-day price heading", () => {
  it("quotes the advertised price over a 30-day month", () => {
    const { container } = render(
      <ProDailyPriceHeading afterPrice="a day to never work again." />,
    );
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"$1 a day to never work again."`,
    );
  });
});

describe("subscription settings", () => {
  it("a subscriber whose plan resolves", () => {
    mockStatus = subscribed(PRO_MONTHLY);
    const { container } = render(<SubscriptionSettings />);
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"Current PlanProEverything GAIA does, in one plan.Active$30 / monthlyNext billing in 24 daysBillingBilling cyclemonthlyNext billing datein 24 daysNovember 1, 2026Last paymentOctober 1, 2026Subscribed sinceSeptember 1, 2026Subscription IDFor support queries···sub_zarWhat's includedChat on iMessage, WhatsApp, Telegram, Slack and DiscordInbox triage and drafted replies every morningMeeting briefs and reminders from your calendarTodos GAIA works on, not just tracksWorkflows that run without youLong jobs it keeps working on while you are awayRemembers what you tell it, oncePriority supportActionsView plans"`,
    );
  });

  it("a ZAR subscriber whose plan does not resolve", () => {
    mockStatus = subscribed(null);
    const { container } = render(<SubscriptionSettings />);
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"Current PlanGAIA ProActive$572.84 / monthlyNext billing in 24 daysBillingBilling cyclemonthlyNext billing datein 24 daysNovember 1, 2026Last paymentOctober 1, 2026Subscribed sinceSeptember 1, 2026Subscription IDFor support queries···sub_zarActionsView plans"`,
    );
  });

  it("a yearly subscriber cancelling", () => {
    mockStatus = subscribed(PRO_YEARLY, {
      currency: "USD",
      recurring_pre_tax_amount: 30000,
      payment_frequency_interval: "Year",
      cancel_at_next_billing_date: true,
    });
    const { container } = render(<SubscriptionSettings />);
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"Current PlanProEverything GAIA does, in one plan.Cancelling$300 / yearlyCancellation scheduled · access until November 1, 2026BillingBilling cycleyearlyNext billing datein 24 daysNovember 1, 2026Last paymentOctober 1, 2026Subscribed sinceSeptember 1, 2026Subscription IDFor support queries···sub_zarWhat's includedChat on iMessage, WhatsApp, Telegram, Slack and DiscordInbox triage and drafted replies every morningMeeting briefs and reminders from your calendarTodos GAIA works on, not just tracksWorkflows that run without youLong jobs it keeps working on while you are awayRemembers what you tell it, oncePriority supportActionsView plans"`,
    );
  });

  it("a never-subscribed user", () => {
    mockStatus = {
      ...subscribed(null),
      subscription: null,
      is_subscribed: false,
      has_ever_subscribed: false,
      plan_type: "free",
    };
    const { container } = render(<SubscriptionSettings />);
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"Current PlanNot subscribedInactiveSubscribe to GAIA Pro to keep chatting and running workflows.Subscribe to GAIA ProSubscribe and you get chat, workflows, priority support and the private Discord.View plans"`,
    );
  });
});

describe("receipts", () => {
  it.each([
    ["USD", 3000],
    ["EUR", 2584],
    ["ZAR", 57284],
    ["INR", 250000],
  ])("prints a %s subscription in its own currency", (currency, amount) => {
    const details = buildReceiptDetails(
      subscribed(PRO_MONTHLY, {
        currency,
        recurring_pre_tax_amount: amount,
      }),
      PRO_MONTHLY,
    );
    const { container } = render(
      <PostPaymentReceipt
        stage="complete"
        planName={details.planName}
        amount={details.amount}
        currency={details.currency}
        billingPeriod={details.billingPeriod}
        nextBillingDate={details.nextBillingDate}
        subscriptionRef={details.subscriptionRef}
        purchasedAt={details.purchasedAt}
        quantity={details.quantity}
        customerEmail="reader@example.com"
      />,
    );
    expect(visibleText(container)).toMatchSnapshot();
  });

  it("previews the clicked plan before the webhook lands", () => {
    expect(buildReceiptDetails(undefined, PRO_YEARLY)).toMatchInlineSnapshot(`
      {
        "amount": 30000,
        "billingPeriod": "yearly",
        "currency": "USD",
        "nextBillingDate": null,
        "planName": "GAIA",
        "purchasedAt": null,
        "quantity": undefined,
        "subscriptionRef": null,
      }
    `);
  });

  it("prints the yearly preview before the webhook lands", () => {
    const details = buildReceiptDetails(undefined, PRO_YEARLY);
    const { container } = render(
      <PostPaymentReceipt
        stage="complete"
        planName={details.planName}
        amount={details.amount}
        currency={details.currency}
        billingPeriod={details.billingPeriod}
        nextBillingDate={details.nextBillingDate}
        subscriptionRef={details.subscriptionRef}
        purchasedAt={details.purchasedAt}
        quantity={details.quantity}
        customerEmail="reader@example.com"
      />,
    );
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"GAIAAnnual subscriptionTotal$300.00Order completeRECEIPTreader@example.comGAIA (Annual)$300.00Total$300.00BillingAnnual subscriptionStatusActiveYou're in. Everything's unlocked, welcome aboard!"`,
    );
  });
});

describe("founder's letter offer", () => {
  it("the offer copy", () => {
    const { container } = render(
      <LetterOffer
        discountCode="THANKYOU40"
        copied={false}
        onCopyCode={vi.fn()}
        onClaim={vi.fn()}
      />,
    );
    expect(visibleText(container)).toMatchInlineSnapshot(
      `"No strings here. Take 40% off with THANKYOU40at checkout. On yearly that's six months free.Claim 40% offCovers your first payment: one month on monthly, a full year on yearly. While it lasts."`,
    );
  });

  it("counts the months it saves from the live yearly price", () => {
    mockPlans = [PRO_MONTHLY, { ...PRO_YEARLY, amount: 24000 }];
    const { container } = render(
      <LetterOffer
        discountCode="THANKYOU40"
        copied={false}
        onCopyCode={vi.fn()}
        onClaim={vi.fn()}
      />,
    );
    expect(visibleText(container)).toContain(
      "On yearly that's seven months free.",
    );
  });

  it("never rounds a part month up into a free one", () => {
    // $270/yr at 40% off is $162: $198 saved, 6.6 months of $30.
    mockPlans = [PRO_MONTHLY, { ...PRO_YEARLY, amount: 27000 }];
    const { container } = render(
      <LetterOffer
        discountCode="THANKYOU40"
        copied={false}
        onCopyCode={vi.fn()}
        onClaim={vi.fn()}
      />,
    );
    expect(visibleText(container)).toContain(
      "On yearly that's six months free.",
    );
  });

  it("names no months while the catalogue is unknown", () => {
    mockPlans = [];
    const { container } = render(
      <LetterOffer
        discountCode="THANKYOU40"
        copied={false}
        onCopyCode={vi.fn()}
        onClaim={vi.fn()}
      />,
    );
    expect(visibleText(container)).not.toContain("free.");
  });

  it("is live until its deadline and gone after", () => {
    expect(isOfferLive(new Date("2026-11-12T23:59:58Z"))).toBe(true);
    expect(isOfferLive(new Date("2026-11-12T23:59:59Z"))).toBe(false);
  });
});

describe("marketing price strings", () => {
  it("the FAQ answers that name a price or a free tier", () => {
    const priced = [...faqData, ...pricingFAQs].filter((faq) =>
      /\$|free/i.test(`${faq.question} ${faq.answer}`),
    );
    expect(priced).toMatchSnapshot();
  });

  it("the structured-data offer", () => {
    expect(generateProductSchema().offers).toMatchInlineSnapshot(`
      {
        "@type": "Offer",
        "availability": "https://schema.org/InStock",
        "description": "GAIA is free to use with open-source self-hosting option",
        "name": "Free Plan",
        "price": "0",
        "priceCurrency": "USD",
      }
    `);
  });
});
