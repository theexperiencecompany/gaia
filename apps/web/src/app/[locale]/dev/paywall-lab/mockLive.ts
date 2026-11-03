/**
 * Stand-ins for what the live pipelines would return, so the lab runs without
 * the API. Every concept that reads these is labelled as mocked on the page.
 */

interface MockEmail {
  from: string;
  subject: string;
  why: string;
  draft: string;
}

interface MockInbox {
  scanned: number;
  noise: number;
  needYou: MockEmail[];
}

interface MockMeeting {
  time: string;
  title: string;
  brief: string;
  /** Set when the meeting needs something from them before it starts. */
  flag?: string;
}

interface MockDay {
  label: string;
  meetings: MockMeeting[];
}

interface MockFinding {
  source: string;
  fact: string;
  action: string;
}

interface MockHomework {
  whoTheyAre: string;
  findings: MockFinding[];
}

export interface LabMock {
  inbox: MockInbox;
  day: MockDay;
  homework: MockHomework;
}

const FOUNDER_MOCK: LabMock = {
  inbox: {
    scanned: 100,
    noise: 41,
    needYou: [
      {
        from: "Priya Shah, Lattice Ventures",
        subject: "Re: term sheet, two questions",
        why: "She wants an answer on the pro-rata clause before Thursday's partner meeting.",
        draft:
          "Hi Priya, happy to keep pro-rata as drafted. On the board seat, can we talk Wednesday at 4? I'll send the revised cap table tonight.",
      },
      {
        from: "Jordan Lee",
        subject: "Offer letter, start date",
        why: "Your design hire asked to start the 18th. Nobody has replied in 3 days.",
        draft:
          "Jordan, the 18th works. Welcome aboard. I'll have laptop and accounts ready by the 16th.",
      },
      {
        from: "Stripe",
        subject: "Action required: verify business details",
        why: "Payouts pause on the 9th if this isn't done. It's the only real one in 14 Stripe emails.",
        draft: "No reply needed. I'll put it on your list for today.",
      },
    ],
  },
  day: {
    label: "Tomorrow, Wednesday",
    meetings: [
      {
        time: "9:30",
        title: "Lattice partner call",
        brief:
          "Priya is pushing for a board seat. Last email, she said pro-rata is fine. Decide the seat before you join.",
        flag: "Needs a decision first",
      },
      {
        time: "12:00",
        title: "Jordan, design onboarding",
        brief: "Start date is the 18th. Accounts aren't set up yet.",
      },
      {
        time: "15:00",
        title: "Weekly team sync",
        brief: "Two launches slipped. Sam flagged the billing export in Slack.",
      },
      {
        time: "17:30",
        title: "Coffee, Alex from Northwind",
        brief: "Met at SaaStr. They're evaluating tools like yours for Q1.",
      },
    ],
  },
  homework: {
    whoTheyAre: "Founder of Fieldnote, 9 people, raised a seed in March",
    findings: [
      {
        source: "LinkedIn",
        fact: "You posted last week that you're hiring a first designer.",
        action: "I'll screen applicants and book calls with the best three.",
      },
      {
        source: "Fieldnote blog",
        fact: "Your last changelog went out 5 weeks ago.",
        action: "I'll draft this month's from what shipped in Linear.",
      },
      {
        source: "X",
        fact: "Two competitors launched AI features this month.",
        action: "I'll track them and send you a Monday note.",
      },
    ],
  },
};

const SALES_MOCK: LabMock = {
  inbox: {
    scanned: 100,
    noise: 38,
    needYou: [
      {
        from: "Maria Gomez, Acme Logistics",
        subject: "Re: pricing for 40 seats",
        why: "She asked for a quote on Monday. A competitor demo is on her calendar Friday.",
        draft:
          "Hi Maria, 40 seats comes to $18,400 a year with onboarding included. I can hold that through Friday. Want me to send the order form?",
      },
      {
        from: "Ben Ito",
        subject: "Can we move our call?",
        why: "He's asking for Thursday instead of today. Your Thursday has a 2pm open.",
        draft: "Thursday at 2 works, Ben. Updated invite coming.",
      },
      {
        from: "Lena, RevOps",
        subject: "Q4 forecast due Friday",
        why: "Your two biggest deals have no next step logged.",
        draft: "No reply needed. I'll pull both deals into your Friday prep.",
      },
    ],
  },
  day: {
    label: "Tomorrow, Wednesday",
    meetings: [
      {
        time: "10:00",
        title: "Discovery, Northwind Freight",
        brief:
          "Ops team of 60. Their VP posted about switching CRMs. Ask what broke with the last one.",
        flag: "Prospect research ready",
      },
      {
        time: "13:30",
        title: "Acme, pricing follow-up",
        brief:
          "Maria has a competitor demo Friday. Lead with onboarding, not price.",
      },
      {
        time: "16:00",
        title: "Pipeline review",
        brief: "Two deals have no next step. Have one ready for each.",
      },
    ],
  },
  homework: {
    whoTheyAre: "Account executive at Relay, selling to logistics teams",
    findings: [
      {
        source: "LinkedIn",
        fact: "Three of your accounts changed heads of ops this quarter.",
        action: "I'll draft an intro to each new decision maker.",
      },
      {
        source: "Relay blog",
        fact: "Your team launched a freight API in October.",
        action: "I'll flag every prospect whose stack it fits.",
      },
      {
        source: "News",
        fact: "Northwind Freight opened two warehouses last month.",
        action: "I'll brief you on it before Wednesday's call.",
      },
    ],
  },
};

const STUDENT_MOCK: LabMock = {
  inbox: {
    scanned: 100,
    noise: 57,
    needYou: [
      {
        from: "Prof. Adeyemi",
        subject: "Thesis draft: comments",
        why: "She wants a revised outline by Monday and asked a direct question.",
        draft:
          "Thank you for the comments. I'll restructure chapter 2 as you suggested and send the revised outline by Sunday evening.",
      },
      {
        from: "Career Center",
        subject: "Your interview is confirmed",
        why: "Thursday 11am. They need your CV re-uploaded by tomorrow.",
        draft: "No reply needed. Re-upload is on your list for tonight.",
      },
      {
        from: "Group project",
        subject: "Who's doing the slides?",
        why: "Four people are waiting on you to pick a section.",
        draft:
          "I'll take the results section and have slides 8 to 12 done by Saturday.",
      },
    ],
  },
  day: {
    label: "Tomorrow, Wednesday",
    meetings: [
      {
        time: "9:00",
        title: "Econometrics lecture",
        brief: "Problem set 4 is due at the start. You haven't opened it.",
        flag: "Due before class",
      },
      {
        time: "14:00",
        title: "Thesis supervision",
        brief: "Bring the revised outline. She asked about your sample size.",
      },
      {
        time: "18:00",
        title: "Group project meetup",
        brief: "You said you'd take the results section.",
      },
    ],
  },
  homework: {
    whoTheyAre: "Economics student, final year",
    findings: [
      {
        source: "University site",
        fact: "Finals start December 9th.",
        action: "I'll build your revision plan backwards from that date.",
      },
      {
        source: "LinkedIn",
        fact: "You applied to two analyst internships.",
        action: "I'll track both and prep you for each interview.",
      },
    ],
  },
};

export const LAB_MOCKS = {
  founder: FOUNDER_MOCK,
  sales: SALES_MOCK,
  student: STUDENT_MOCK,
} as const;
