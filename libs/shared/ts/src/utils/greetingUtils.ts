// Utility functions for time-based greetings. Platform-agnostic.

export const getSimpleTimeGreeting = (): string => {
  const currentHour = new Date().getHours();

  if (currentHour >= 5 && currentHour < 12) {
    return "Good morning";
  } else if (currentHour >= 12 && currentHour < 17) {
    return "Good afternoon";
  } else if (currentHour >= 17 && currentHour < 21) {
    return "Good evening";
  } else {
    return "Good night";
  }
};

const getTimeBasedGreeting = (
  userName?: string,
  includeName: boolean = true,
): string => {
  const currentHour = new Date().getHours();

  const morningGreetings = [
    "What's brewing today{name}?",
    "Rise and conquer{name}!",
    "Today's mission{name}?",
    "Morning{name}, champion!",
    "Let's make magic happen{name}",
    "Fresh day, fresh possibilities{name}",
    "What adventure awaits{name}?",
    "Time to shine bright{name}",
    "Ready to crush it{name}?",
    "New day, new wins{name}",
    "Morning energy activated{name}",
    "What's the game plan{name}?",
    "Sunrise = fresh start{name}",
    "Let's build something cool{name}",
  ];

  const afternoonGreetings = [
    "Afternoon check-in{name}. What's next?",
    "Back at it{name}. Keep pushing.",
    "Midday momentum{name}, let's move.",
    "How's the grind going{name}?",
    "Push through the slump{name}.",
    "Let's close some loops{name}.",
    "Keep stacking wins{name}.",
    "Any progress updates{name}?",
    "Execution mode: ON{name}.",
    "Time to refocus{name}.",
    "Dial it back in{name}.",
    "Momentum compounds{name}.",
    "Still building strong{name}?",
    "Halfway there{name}, keep going.",
    "Let's lock in the second half{name}.",
  ];

  const eveningGreetings = [
    "Evening grind{name}, what's left?",
    "Day's endgame{name}. One last push?",
    "Time to finish strong{name}.",
    "Evening hustle check{name}.",
    "Closing hours = clutch hours{name}.",
    "Strong finish > strong start{name}.",
    "Any loose ends to wrap{name}?",
    "End the day on your terms{name}.",
    "Final sprint of the day{name}.",
    "Keep it sharp till the end{name}.",
    "What's tonight's plan{name}?",
    "Last task before rest{name}?",
    "Push through, then recharge{name}.",
    "Evening clarity unlocked{name}.",
    "Let's seal today's wins{name}.",
  ];

  const nightGreetings = [
    "Late hours, clear thoughts{name}.",
    "What's the midnight mission{name}?",
    "Silence fuels creativity{name}.",
    "Night grind = no distractions{name}.",
    "Moonlight mode: ON{name}.",
    "Ideas flow better after dark{name}.",
    "Still cooking something{name}?",
    "Midnight clarity unlocked{name}.",
    "Night shift in progress{name}.",
    "Who needs 9–5 anyway{name}?",
    "Dark hours, bright ideas{name}.",
    "World's quiet, your turn{name}.",
    "Night = deep work zone{name}.",
    "Late night energy unlocked{name}.",
    "Tomorrow prep starts now{name}.",
  ];

  let greetings: string[];
  if (currentHour >= 5 && currentHour < 12) {
    greetings = morningGreetings;
  } else if (currentHour >= 12 && currentHour < 17) {
    greetings = afternoonGreetings;
  } else if (currentHour >= 17 && currentHour < 21) {
    greetings = eveningGreetings;
  } else {
    greetings = nightGreetings;
  }

  const randomIndex = Math.floor(Math.random() * greetings.length);
  const template = greetings[randomIndex];

  if (!includeName || !userName || userName.trim() === "") {
    return template.replace("{name}", "");
  }

  const firstName = userName.split(" ")[0];
  return template.replace("{name}", `, ${firstName}`);
};

export const getCompleteTimeBasedGreeting = (userName?: string): string => {
  return getTimeBasedGreeting(userName);
};
