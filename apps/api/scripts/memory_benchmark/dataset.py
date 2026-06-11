"""Hard benchmark scenarios for the GAIA memory engine.

Each scenario is a dict with:
  id          : str  — unique slug
  category    : str  — weakness category being probed
  turns       : list[dict]  with keys role/content/day_offset
  probes      : list[dict]  with keys query/must_contain/must_not_contain/description/is_negative

Design philosophy: find what breaks, not what passes.
- Indirect/paraphrase probes share ZERO vocabulary with the stored fact.
- Distractor scenarios have 3 entities with overlapping attributes.
- Negative abstention probes ask for things never stated — must return empty.
- Contradiction/update scenarios ensure OLD facts are NOT recalled.
- Temporal scenarios with forget_after: engine stores them with no built-in expiry
  (no forget_after param in retain), so we test whether stale facts bleed through.
"""

from __future__ import annotations

SCENARIOS: list[dict] = [
    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY 1: SINGLE_HOP — basic factual recall
    # ─────────────────────────────────────────────────────────────────────────
    {
        "id": "sh_01_birthday",
        "category": "SINGLE_HOP",
        "turns": [
            {
                "role": "user",
                "content": "My birthday is on March 15th.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it, I'll remember your birthday is March 15th.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "When is my birthday?",
                "must_contain": ["march", "15"],
                "must_not_contain": [],
                "description": "Direct birthday recall",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "sh_02_diet",
        "category": "SINGLE_HOP",
        "turns": [
            {
                "role": "user",
                "content": "I'm strictly vegan — no meat, no dairy, no eggs.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Noted, you're strictly vegan.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What is my diet?",
                "must_contain": ["vegan"],
                "must_not_contain": ["omnivore", "vegetarian", "carnivore"],
                "description": "Diet preference recall",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "sh_03_employer",
        "category": "SINGLE_HOP",
        "turns": [
            {
                "role": "user",
                "content": "I work as a senior software engineer at Stripe.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "I'll remember you work at Stripe as a senior software engineer.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "Where do I work?",
                "must_contain": ["stripe"],
                "must_not_contain": ["google", "amazon", "meta"],
                "description": "Employer recall",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "sh_04_pet_name",
        "category": "SINGLE_HOP",
        "turns": [
            {
                "role": "user",
                "content": "My cat is named Mochi. She's a 3-year-old tortoiseshell.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Mochi sounds adorable!",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What is my cat's name?",
                "must_contain": ["mochi"],
                "must_not_contain": [],
                "description": "Pet name recall",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "sh_05_city",
        "category": "SINGLE_HOP",
        "turns": [
            {
                "role": "user",
                "content": "I live in Austin, Texas.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it, you're in Austin, Texas.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What city do I live in?",
                "must_contain": ["austin"],
                "must_not_contain": ["houston", "dallas", "san antonio"],
                "description": "City of residence recall",
                "is_negative": False,
            }
        ],
    },
    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY 2: MULTI_SESSION_CONSOLIDATION — fact spread across 3 sessions
    # ─────────────────────────────────────────────────────────────────────────
    {
        "id": "ms_01_project_stack",
        "category": "MULTI_SESSION_CONSOLIDATION",
        "turns": [
            # Session 1: introduces the project
            {
                "role": "user",
                "content": "I'm building a side project called Lumen.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Tell me more about Lumen!",
                "day_offset": 0,
            },
            # Session 2: adds tech stack
            {
                "role": "user",
                "content": "Lumen is a React Native app.",
                "day_offset": 5,
            },
            {
                "role": "assistant",
                "content": "Got it, React Native.",
                "day_offset": 5,
            },
            # Session 3: adds database choice
            {
                "role": "user",
                "content": "For Lumen's backend, I'm using Supabase.",
                "day_offset": 10,
            },
            {
                "role": "assistant",
                "content": "Supabase is a solid choice.",
                "day_offset": 10,
            },
        ],
        "probes": [
            {
                "query": "What is the Lumen project?",
                "must_contain": ["lumen"],
                "must_not_contain": [],
                "description": "Project name consolidation",
                "is_negative": False,
            },
            {
                "query": "What database does Lumen use?",
                "must_contain": ["supabase"],
                "must_not_contain": ["firebase", "postgres", "mysql"],
                "description": "Database detail from session 3",
                "is_negative": False,
            },
        ],
    },
    {
        "id": "ms_02_medical_history",
        "category": "MULTI_SESSION_CONSOLIDATION",
        "turns": [
            {
                "role": "user",
                "content": "I have a nut allergy.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "I'll note your nut allergy.",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "I also have mild asthma.",
                "day_offset": 7,
            },
            {
                "role": "assistant",
                "content": "Noted: nut allergy and mild asthma.",
                "day_offset": 7,
            },
            {
                "role": "user",
                "content": "Oh, and I take 10mg of Cetirizine daily for allergies.",
                "day_offset": 14,
            },
            {
                "role": "assistant",
                "content": "Got it, 10mg Cetirizine daily.",
                "day_offset": 14,
            },
        ],
        "probes": [
            {
                "query": "What medications do I take?",
                "must_contain": ["cetirizine"],
                "must_not_contain": [],
                "description": "Medication from session 3",
                "is_negative": False,
            },
            {
                "query": "Do I have any allergies or medical conditions?",
                "must_contain": ["nut"],
                "must_not_contain": [],
                "description": "Allergy from session 1",
                "is_negative": False,
            },
        ],
    },
    {
        "id": "ms_03_girlfriend_context",
        "category": "MULTI_SESSION_CONSOLIDATION",
        "turns": [
            {
                "role": "user",
                "content": "My girlfriend's name is Priya.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Nice to know about Priya!",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "Priya is a dentist.",
                "day_offset": 3,
            },
            {
                "role": "assistant",
                "content": "Got it, Priya is a dentist.",
                "day_offset": 3,
            },
            {
                "role": "user",
                "content": "Priya's birthday is October 2nd.",
                "day_offset": 20,
            },
            {
                "role": "assistant",
                "content": "I'll remember Priya's birthday is October 2nd.",
                "day_offset": 20,
            },
        ],
        "probes": [
            {
                "query": "What is my girlfriend's birthday?",
                "must_contain": ["october", "priya"],
                "must_not_contain": [],
                "description": "Girlfriend birthday from session 3",
                "is_negative": False,
            },
            {
                "query": "What does Priya do for work?",
                "must_contain": ["dentist"],
                "must_not_contain": ["doctor", "nurse", "engineer"],
                "description": "Girlfriend's profession from session 2",
                "is_negative": False,
            },
        ],
    },
    {
        "id": "ms_04_home_purchase",
        "category": "MULTI_SESSION_CONSOLIDATION",
        "turns": [
            {
                "role": "user",
                "content": "I'm thinking of buying a house.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "That's exciting! Any budget in mind?",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "My budget is around $750,000.",
                "day_offset": 2,
            },
            {
                "role": "assistant",
                "content": "$750k, got it.",
                "day_offset": 2,
            },
            {
                "role": "user",
                "content": "I found a great place in the Zilker neighborhood.",
                "day_offset": 15,
            },
            {
                "role": "assistant",
                "content": "Zilker is a great area!",
                "day_offset": 15,
            },
        ],
        "probes": [
            {
                "query": "What neighborhood am I looking at for my house?",
                "must_contain": ["zilker"],
                "must_not_contain": [],
                "description": "Neighborhood from session 3",
                "is_negative": False,
            },
        ],
    },
    {
        "id": "ms_05_fitness_goals",
        "category": "MULTI_SESSION_CONSOLIDATION",
        "turns": [
            {
                "role": "user",
                "content": "I started a running program last month.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "That's great!",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "My goal is to run a 5K in under 25 minutes.",
                "day_offset": 10,
            },
            {
                "role": "assistant",
                "content": "Sub-25 minute 5K is achievable.",
                "day_offset": 10,
            },
            {
                "role": "user",
                "content": "I run every Tuesday and Thursday at 6am.",
                "day_offset": 20,
            },
            {
                "role": "assistant",
                "content": "Got it: Tuesday and Thursday mornings.",
                "day_offset": 20,
            },
        ],
        "probes": [
            {
                "query": "What is my fitness goal?",
                "must_contain": ["5k", "25"],
                "must_not_contain": [],
                "description": "Running goal from session 2",
                "is_negative": False,
            },
        ],
    },
    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY 3: TEMPORAL_REASONING — date-relative facts
    # Note: engine has no built-in forget_after via retain() — these test
    # whether the engine correctly handles recency of facts.
    # ─────────────────────────────────────────────────────────────────────────
    {
        "id": "tr_01_event_already_passed",
        "category": "TEMPORAL_REASONING",
        "turns": [
            {
                "role": "user",
                "content": "I have a job interview at Google on January 5th, 2026.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "I'll remember your Google interview on January 5th.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "Do I have any upcoming interviews?",
                # The interview date (Jan 5, 2026) is in the past relative to base_date (2026-01-10)
                # The engine should ideally not surface this as "upcoming" — but it likely will
                # since there's no forget_after logic in retain(). This tests over-recall.
                "must_contain": [],
                "must_not_contain": [],
                "description": "Past interview may incorrectly appear as upcoming (engine weakness)",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "tr_02_recent_vs_old",
        "category": "TEMPORAL_REASONING",
        "turns": [
            # Older fact (day 0)
            {
                "role": "user",
                "content": "My current project deadline is March 1st, 2026.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "March 1st deadline noted.",
                "day_offset": 0,
            },
            # Newer fact (day 60) overrides deadline
            {
                "role": "user",
                "content": "The deadline got pushed to April 15th, 2026.",
                "day_offset": 60,
            },
            {
                "role": "assistant",
                "content": "Got it, new deadline is April 15th.",
                "day_offset": 60,
            },
        ],
        "probes": [
            {
                "query": "When is my project deadline?",
                "must_contain": ["april", "15"],
                "must_not_contain": ["march", "march 1"],
                "description": "Updated deadline must supersede old one",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "tr_03_age_birthday_math",
        "category": "TEMPORAL_REASONING",
        "turns": [
            {
                "role": "user",
                "content": "I was born on June 3rd, 1992.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it, born June 3, 1992.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What year was I born?",
                "must_contain": ["1992"],
                "must_not_contain": ["1991", "1993", "2000"],
                "description": "Birth year recall",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "tr_04_subscription_expiry",
        "category": "TEMPORAL_REASONING",
        "turns": [
            {
                "role": "user",
                "content": "My Adobe Creative Cloud subscription expires on February 28, 2026.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Adobe CC expires Feb 28 2026.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "When does my Adobe subscription expire?",
                "must_contain": ["february", "2026"],
                "must_not_contain": ["march", "january"],
                "description": "Subscription expiry date recall",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "tr_05_sequence_of_events",
        "category": "TEMPORAL_REASONING",
        "turns": [
            {
                "role": "user",
                "content": "Last week I got promoted to Staff Engineer.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Congratulations on the Staff Engineer promotion!",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "Before the promotion I was a Senior Engineer for 3 years.",
                "day_offset": 1,
            },
            {
                "role": "assistant",
                "content": "Three years as Senior, now Staff — solid progression.",
                "day_offset": 1,
            },
        ],
        "probes": [
            {
                "query": "What is my current job title?",
                "must_contain": ["staff"],
                "must_not_contain": ["senior"],
                "description": "Current title is Staff, not Senior (most recent state)",
                "is_negative": False,
            }
        ],
    },
    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY 4: CONTRADICTION_UPDATE — fact updated, old must NOT surface
    # ─────────────────────────────────────────────────────────────────────────
    {
        "id": "cu_01_moved_cities",
        "category": "CONTRADICTION_UPDATE",
        "turns": [
            {
                "role": "user",
                "content": "I live in San Francisco.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it, San Francisco.",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "I just moved to Seattle last month.",
                "day_offset": 40,
            },
            {
                "role": "assistant",
                "content": "Got it, you're now in Seattle.",
                "day_offset": 40,
            },
        ],
        "probes": [
            {
                "query": "Where do I live?",
                "must_contain": ["seattle"],
                "must_not_contain": ["san francisco", "sf"],
                "description": "Current city is Seattle; old SF fact must not surface",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "cu_02_changed_jobs",
        "category": "CONTRADICTION_UPDATE",
        "turns": [
            {
                "role": "user",
                "content": "I work at Twilio.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it, Twilio.",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "I quit Twilio and just started at Databricks.",
                "day_offset": 60,
            },
            {
                "role": "assistant",
                "content": "Congratulations on joining Databricks!",
                "day_offset": 60,
            },
        ],
        "probes": [
            {
                "query": "Where do I work?",
                "must_contain": ["databricks"],
                "must_not_contain": ["twilio"],
                "description": "Current employer is Databricks; Twilio is old",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "cu_03_diet_change",
        "category": "CONTRADICTION_UPDATE",
        "turns": [
            {
                "role": "user",
                "content": "I'm a vegetarian.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it, vegetarian.",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "I went vegan 3 months ago — no more dairy or eggs either.",
                "day_offset": 30,
            },
            {
                "role": "assistant",
                "content": "Got it, fully vegan now.",
                "day_offset": 30,
            },
        ],
        "probes": [
            {
                "query": "What is my diet?",
                "must_contain": ["vegan"],
                "must_not_contain": ["vegetarian"],
                "description": "Diet updated to vegan; old vegetarian must not dominate",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "cu_04_relationship_status",
        "category": "CONTRADICTION_UPDATE",
        "turns": [
            {
                "role": "user",
                "content": "I'm single.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it.",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "I started dating someone — her name is Leila.",
                "day_offset": 45,
            },
            {
                "role": "assistant",
                "content": "Congratulations! What's Leila like?",
                "day_offset": 45,
            },
        ],
        "probes": [
            {
                "query": "What is my relationship status?",
                "must_contain": ["leila"],
                "must_not_contain": ["single"],
                "description": "Now dating Leila; 'single' must not surface",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "cu_05_phone_number",
        "category": "CONTRADICTION_UPDATE",
        "turns": [
            {
                "role": "user",
                "content": "My phone number is +1-415-555-0101.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Saved: +1-415-555-0101.",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "I got a new number: +1-737-555-0234.",
                "day_offset": 90,
            },
            {
                "role": "assistant",
                "content": "Updated: +1-737-555-0234.",
                "day_offset": 90,
            },
        ],
        "probes": [
            {
                "query": "What is my phone number?",
                "must_contain": ["737"],
                "must_not_contain": ["415"],
                "description": "New phone number; old must not surface",
                "is_negative": False,
            }
        ],
    },
    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY 5: PREFERENCE_PERSISTENCE — subtle prefs stated once
    # ─────────────────────────────────────────────────────────────────────────
    {
        "id": "pp_01_coffee_order",
        "category": "PREFERENCE_PERSISTENCE",
        "turns": [
            {
                "role": "user",
                "content": "Can you help me find coffee shops? I always get an oat milk cortado.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Sure! I'll remember you like oat milk cortados.",
                "day_offset": 0,
            },
            # Filler session to test persistence
            {
                "role": "user",
                "content": "What's the weather like?",
                "day_offset": 30,
            },
            {
                "role": "assistant",
                "content": "I don't have real-time weather data.",
                "day_offset": 30,
            },
        ],
        "probes": [
            {
                "query": "What coffee do I usually drink?",
                "must_contain": ["oat", "cortado"],
                "must_not_contain": ["latte", "americano", "espresso"],
                "description": "Coffee preference stated once, probed 30 days later",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "pp_02_communication_style",
        "category": "PREFERENCE_PERSISTENCE",
        "turns": [
            {
                "role": "user",
                "content": "I hate when people say 'I hope this email finds you well'. Just get to the point.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Noted — direct, no filler phrases.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "How do I prefer written communication?",
                "must_contain": ["direct"],
                "must_not_contain": [],
                "description": "Communication style preference",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "pp_03_meeting_preference",
        "category": "PREFERENCE_PERSISTENCE",
        "turns": [
            {
                "role": "user",
                "content": "I never take meetings before 10am. My brain doesn't work until then.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "No meetings before 10am — got it.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What are my scheduling constraints?",
                "must_contain": ["10"],
                "must_not_contain": [],
                "description": "Meeting time preference",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "pp_04_music_taste",
        "category": "PREFERENCE_PERSISTENCE",
        "turns": [
            {
                "role": "user",
                "content": "I love jazz — especially 1960s Blue Note stuff. Miles Davis, Coltrane.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Classic taste! Miles Davis and Coltrane.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What kind of music do I like?",
                "must_contain": ["jazz"],
                "must_not_contain": ["rock", "pop", "hip hop"],
                "description": "Music preference recall",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "pp_05_travel_style",
        "category": "PREFERENCE_PERSISTENCE",
        "turns": [
            {
                "role": "user",
                "content": "When I travel I always book window seats and prefer aisle exit rows. I can't do middle seats.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Window seat, exit row — got it.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What seat do I prefer on flights?",
                "must_contain": ["window"],
                "must_not_contain": ["middle", "aisle"],
                "description": "Flight seating preference",
                "is_negative": False,
            }
        ],
    },
    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY 6: INDIRECT_PARAPHRASE — probe shares NO vocabulary with stored fact
    # ─────────────────────────────────────────────────────────────────────────
    {
        "id": "ip_01_employment_paraphrase",
        "category": "INDIRECT_PARAPHRASE",
        "turns": [
            {
                "role": "user",
                "content": "I'm a software engineer at Stripe.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "Who pays my salary and what role am I in professionally?",
                # No 'software', 'engineer', or 'stripe' in the query
                "must_contain": ["stripe"],
                "must_not_contain": [],
                "description": "Employment probed with zero-overlap vocabulary",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "ip_02_diet_paraphrase",
        "category": "INDIRECT_PARAPHRASE",
        "turns": [
            {
                "role": "user",
                "content": "I'm strictly vegan — no animal products whatsoever.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Noted.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "Can I eat a cheeseburger?",
                # 'cheeseburger' has zero overlap with 'vegan', 'animal products'
                "must_contain": ["vegan"],
                "must_not_contain": [],
                "description": "Diet recalled via a specific excluded food question",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "ip_03_allergy_paraphrase",
        "category": "INDIRECT_PARAPHRASE",
        "turns": [
            {
                "role": "user",
                "content": "I'm allergic to shellfish — shrimp, lobster, crab.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it, shellfish allergy.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "Is there anything I should avoid at a seafood restaurant?",
                # No 'allerg', 'shellfish', 'shrimp', 'lobster', 'crab' in query
                "must_contain": ["shellfish"],
                "must_not_contain": [],
                "description": "Allergy recalled via restaurant avoidance framing",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "ip_04_location_paraphrase",
        "category": "INDIRECT_PARAPHRASE",
        "turns": [
            {
                "role": "user",
                "content": "I'm based in Amsterdam.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it, Amsterdam.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What timezone am I in?",
                # 'timezone' not mentioned at all; requires knowing Amsterdam = CET
                "must_contain": ["amsterdam"],
                "must_not_contain": [],
                "description": "Location recalled via timezone inference question",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "ip_05_skill_paraphrase",
        "category": "INDIRECT_PARAPHRASE",
        "turns": [
            {
                "role": "user",
                "content": "I've been writing Python professionally for 8 years.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Eight years of Python — solid.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "Do I know how to code?",
                # 'code', 'coding' not in stored fact; 'Python', 'professionally', '8 years' not in query
                "must_contain": ["python"],
                "must_not_contain": [],
                "description": "Programming skill recalled via generic coding question",
                "is_negative": False,
            }
        ],
    },
    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY 7: DISTRACTOR_ROBUSTNESS — 3 similar entities, must get right one
    # ─────────────────────────────────────────────────────────────────────────
    {
        "id": "dr_01_three_siblings",
        "category": "DISTRACTOR_ROBUSTNESS",
        "turns": [
            {
                "role": "user",
                "content": "I have three brothers: Jake (28), Marcus (32), and Eli (25).",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it: Jake 28, Marcus 32, Eli 25.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "How old is Marcus?",
                "must_contain": ["32"],
                "must_not_contain": ["28", "25"],
                "description": "Marcus's age, not Jake's (28) or Eli's (25)",
                "is_negative": False,
            },
            {
                "query": "Which of my brothers is youngest?",
                "must_contain": ["eli", "25"],
                "must_not_contain": ["jake", "marcus"],
                "description": "Youngest sibling identification",
                "is_negative": False,
            },
        ],
    },
    {
        "id": "dr_02_three_projects",
        "category": "DISTRACTOR_ROBUSTNESS",
        "turns": [
            {
                "role": "user",
                "content": "I'm working on three projects: Atlas (deadline next week), Beacon (paused), and Comet (just kicked off).",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it: Atlas urgent, Beacon paused, Comet new.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "Which project is paused?",
                "must_contain": ["beacon"],
                "must_not_contain": ["atlas", "comet"],
                "description": "Paused project is Beacon, not Atlas or Comet",
                "is_negative": False,
            },
            {
                "query": "Which project has a deadline coming up soon?",
                "must_contain": ["atlas"],
                "must_not_contain": ["beacon", "comet"],
                "description": "Urgent project is Atlas",
                "is_negative": False,
            },
        ],
    },
    {
        "id": "dr_03_three_colleagues",
        "category": "DISTRACTOR_ROBUSTNESS",
        "turns": [
            {
                "role": "user",
                "content": "At work I deal with three main people: Sarah (my manager), Tom (PM on my team), and Alex (engineer I mentor).",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it: Sarah is your manager, Tom is the PM, Alex is the mentee.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "Who is my manager at work?",
                "must_contain": ["sarah"],
                "must_not_contain": ["tom", "alex"],
                "description": "Manager is Sarah, not Tom or Alex",
                "is_negative": False,
            },
            {
                "query": "Who do I mentor?",
                "must_contain": ["alex"],
                "must_not_contain": ["sarah", "tom"],
                "description": "Mentee is Alex",
                "is_negative": False,
            },
        ],
    },
    {
        "id": "dr_04_three_addresses",
        "category": "DISTRACTOR_ROBUSTNESS",
        "turns": [
            {
                "role": "user",
                "content": "I live at 14 Oak Street. My office is at 200 Tech Blvd. My parents live at 7 Maple Ave.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it: home 14 Oak, office 200 Tech Blvd, parents 7 Maple.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What is my home address?",
                "must_contain": ["14", "oak"],
                "must_not_contain": ["200", "tech", "maple"],
                "description": "Home address, not office or parents'",
                "is_negative": False,
            },
        ],
    },
    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY 8: NEGATIVE_ABSTENTION — probe something never stated
    # The engine MUST return empty/nothing (no hallucination)
    # ─────────────────────────────────────────────────────────────────────────
    {
        "id": "na_01_never_stated_height",
        "category": "NEGATIVE_ABSTENTION",
        "turns": [
            {
                "role": "user",
                "content": "I enjoy hiking on weekends.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Nice, weekend hiking!",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "How tall am I?",
                "must_contain": [],
                "must_not_contain": [],
                "description": "Height never stated — must return nothing specific",
                "is_negative": True,
            }
        ],
    },
    {
        "id": "na_02_never_stated_income",
        "category": "NEGATIVE_ABSTENTION",
        "turns": [
            {
                "role": "user",
                "content": "I work as a graphic designer.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What is my annual salary?",
                "must_contain": [],
                "must_not_contain": [],
                "description": "Salary never mentioned — engine must not fabricate",
                "is_negative": True,
            }
        ],
    },
    {
        "id": "na_03_never_stated_car",
        "category": "NEGATIVE_ABSTENTION",
        "turns": [
            {
                "role": "user",
                "content": "I commute to work every day.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Daily commute noted.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What kind of car do I drive?",
                "must_contain": [],
                "must_not_contain": [],
                "description": "Car type never stated — must not hallucinate a make/model",
                "is_negative": True,
            }
        ],
    },
    {
        "id": "na_04_never_stated_spouse",
        "category": "NEGATIVE_ABSTENTION",
        "turns": [
            {
                "role": "user",
                "content": "I have two kids, ages 4 and 7.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it, two kids.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What is my spouse's name?",
                "must_contain": [],
                "must_not_contain": [],
                "description": "Spouse never named — must not assume or hallucinate",
                "is_negative": True,
            }
        ],
    },
    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY 9: IDENTITY_MAPPINGS — usernames/emails/IDs from tool calls
    # ─────────────────────────────────────────────────────────────────────────
    {
        "id": "id_01_github_username",
        "category": "IDENTITY_MAPPINGS",
        "turns": [
            {
                "role": "user",
                "content": "My GitHub username is aryanranderiya.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it: GitHub username aryanranderiya.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What is my GitHub username?",
                "must_contain": ["aryanranderiya"],
                "must_not_contain": [],
                "description": "GitHub username recall",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "id_02_email_address",
        "category": "IDENTITY_MAPPINGS",
        "turns": [
            {
                "role": "user",
                "content": "My work email is j.smith@acme.corp.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Work email saved: j.smith@acme.corp.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What is my work email address?",
                "must_contain": ["j.smith", "acme"],
                "must_not_contain": [],
                "description": "Work email recall",
                "is_negative": False,
            }
        ],
    },
    {
        "id": "id_03_api_key_hint",
        "category": "IDENTITY_MAPPINGS",
        "turns": [
            {
                "role": "user",
                "content": "My Notion workspace ID is abc-123-xyz. I'll need it to integrate with GAIA.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Notion workspace ID abc-123-xyz stored.",
                "day_offset": 0,
            },
        ],
        "probes": [
            {
                "query": "What is my Notion workspace ID?",
                "must_contain": ["abc-123-xyz"],
                "must_not_contain": [],
                "description": "Notion workspace ID recall",
                "is_negative": False,
            }
        ],
    },
    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY 10: KNOWLEDGE_GRAPH — multi-entity requiring 2 linked facts
    # ─────────────────────────────────────────────────────────────────────────
    {
        "id": "kg_01_person_role_company",
        "category": "KNOWLEDGE_GRAPH",
        "turns": [
            {
                "role": "user",
                "content": "My co-founder is Dani Kowalski. She's the CTO.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it: Dani Kowalski, CTO, your co-founder.",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "We're building a company called Neon Labs together.",
                "day_offset": 2,
            },
            {
                "role": "assistant",
                "content": "Neon Labs — got it.",
                "day_offset": 2,
            },
        ],
        "probes": [
            {
                "query": "Who is the CTO of Neon Labs?",
                # Requires linking: Dani = CTO + Neon Labs = our company
                "must_contain": ["dani"],
                "must_not_contain": [],
                "description": "Person-role-company cross-link",
                "is_negative": False,
            },
            {
                "query": "What company am I building with Dani?",
                "must_contain": ["neon"],
                "must_not_contain": [],
                "description": "Company linked to named person",
                "is_negative": False,
            },
        ],
    },
    {
        "id": "kg_02_event_person_location",
        "category": "KNOWLEDGE_GRAPH",
        "turns": [
            {
                "role": "user",
                "content": "My mom's name is Sunita. She lives in Ahmedabad.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it: Sunita, Ahmedabad.",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "I'm flying to visit Sunita in March.",
                "day_offset": 5,
            },
            {
                "role": "assistant",
                "content": "Trip to Ahmedabad in March to see Sunita.",
                "day_offset": 5,
            },
        ],
        "probes": [
            {
                "query": "Where am I flying in March?",
                "must_contain": ["ahmedabad"],
                "must_not_contain": [],
                "description": "Flight destination linked to Sunita's location",
                "is_negative": False,
            },
        ],
    },
    {
        "id": "kg_03_product_owner",
        "category": "KNOWLEDGE_GRAPH",
        "turns": [
            {
                "role": "user",
                "content": "The main product I'm responsible for at work is called Orion.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it: you own Orion.",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "Orion's biggest customer is NovaTech Inc.",
                "day_offset": 3,
            },
            {
                "role": "assistant",
                "content": "NovaTech Inc. is Orion's biggest customer.",
                "day_offset": 3,
            },
        ],
        "probes": [
            {
                "query": "Who is the biggest customer of the product I own?",
                "must_contain": ["novatech"],
                "must_not_contain": [],
                "description": "Customer linked through product ownership",
                "is_negative": False,
            },
        ],
    },
    {
        "id": "kg_04_investment_portfolio",
        "category": "KNOWLEDGE_GRAPH",
        "turns": [
            {
                "role": "user",
                "content": "I invested in a startup called Quill AI two years ago.",
                "day_offset": 0,
            },
            {
                "role": "assistant",
                "content": "Got it: Quill AI investment.",
                "day_offset": 0,
            },
            {
                "role": "user",
                "content": "Quill AI just raised a Series A. They're now valued at $40M.",
                "day_offset": 60,
            },
            {
                "role": "assistant",
                "content": "Quill AI Series A at $40M valuation.",
                "day_offset": 60,
            },
        ],
        "probes": [
            {
                "query": "What is the valuation of my investment in Quill AI?",
                "must_contain": ["40"],
                "must_not_contain": [],
                "description": "Investment valuation after funding round update",
                "is_negative": False,
            },
        ],
    },
]

# Validate no duplicate IDs at import time
_ids = [s["id"] for s in SCENARIOS]
assert len(_ids) == len(set(_ids)), (
    f"Duplicate scenario IDs: {[x for x in _ids if _ids.count(x) > 1]}"
)
assert len(SCENARIOS) >= 40, f"Need at least 40 scenarios, got {len(SCENARIOS)}"
