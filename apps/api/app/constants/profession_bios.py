"""Profession-based bio templates for users without Gmail integration."""

import random
from typing import Dict, List, Tuple

# Profession enum matching frontend options
PROFESSIONS = (
    "student",
    "teacher",
    "engineer",
    "developer",
    "designer",
    "manager",
    "consultant",
    "entrepreneur",
    "researcher",
    "writer",
    "artist",
    "doctor",
    "lawyer",
    "accountant",
    "sales",
    "marketing",
    "analyst",
    "freelancer",
    "retired",
    "other",
)

# Creative bio templates per profession
# {name} will be replaced with user's name
PROFESSION_BIOS: Dict[str, List[str]] = {
    "student": [
        "{name} is a ambitious student harnessing GAIA's intelligent automation to ace deadlines, manage study schedules, and turn chaos into straight A's. Currently mastering the art of productivity, one automated workflow at a time.",
        "Meet {name}, a student who discovered that GAIA is basically the study buddy who never sleeps, never judges your 3am panic sessions, and always remembers when assignments are due. Transforming academic stress into organized success.",
        "{name} is rewriting the student playbook with GAIA's AI-powered assistance. From lecture notes to lab reports, they're proving that smart automation beats all-nighters every single time.",
        "Student by day, productivity ninja by night - {name} leverages GAIA to juggle coursework, projects, and sanity with unprecedented grace. Who said you can't have it all in college?",
        "{name} is that student who actually has their life together, thanks to GAIA. While others drown in deadlines, they're surfing through semesters with AI-powered precision and a suspicious amount of free time.",
        "Armed with GAIA and unlimited ambition, {name} is revolutionizing what it means to be a student. Less cramming, more creating. Less stress, more success.",
    ],
    "teacher": [
        "{name} is an innovative teacher using GAIA to revolutionize education, one automated lesson plan at a time. Making grading less painful and inspiration more plentiful since joining the AI revolution.",
        "Educator extraordinaire {name} has discovered the teaching superpower called GAIA. Now creating engaging content, managing classrooms, and inspiring minds without the usual burnout.",
        "{name} is that teacher who actually has time for creative lesson planning, thanks to GAIA handling the administrative avalanche. Transforming education with AI-powered efficiency.",
        "Meet {name}, a teacher who believes in working smarter, not harder. With GAIA automating the mundane, they're free to focus on what matters: shaping brilliant minds.",
        "{name} is pioneering the future of education with GAIA's intelligent assistance. Less paperwork, more eureka moments. Less admin, more inspiration.",
        "Visionary educator {name} leverages GAIA to create magical learning experiences while maintaining work-life balance. Yes, it's possible, and yes, other teachers are jealous.",
        "{name} teaches by day and lets GAIA handle the rest. From automated grading to streamlined communication, they're proving that AI and education are a match made in academic heaven.",
    ],
    "engineer": [
        "{name} is an engineer who solves complex problems before breakfast and automates the rest with GAIA. Building tomorrow's solutions with today's most intelligent AI assistant.",
        "Technical wizard {name} combines engineering brilliance with GAIA's automation prowess. The result? Systems that run themselves and solutions that scale effortlessly.",
        "{name} engineers the impossible and delegates the routine to GAIA. Currently optimizing everything from code deployments to coffee schedules with algorithmic precision.",
        "Meet {name}, an engineer who treats inefficiency like a bug to be fixed. With GAIA as their co-pilot, they're architecting a future where everything just works.",
        "{name} is that engineer who automates their automations. With GAIA handling the pipeline, they're free to tackle the problems that actually require human creativity.",
        "Problem-solver {name} leverages GAIA to transform engineering challenges into elegant solutions. Less debugging, more building. Less maintenance, more innovation.",
    ],
    "developer": [
        "{name} is a developer who writes code that writes itself (almost). With GAIA handling the repetitive tasks, they're free to architect digital dreams and debug reality.",
        "Code poet {name} has discovered the ultimate pair programmer: GAIA. Together, they're shipping features faster than you can say 'continuous deployment'.",
        "{name} is that developer who actually has time for side projects, thanks to GAIA automating everything from code reviews to coffee orders. Living the dream, one commit at a time.",
        "Full-stack wizard {name} leverages GAIA to handle the stack overflow of daily tasks. More creating, less configuring. More shipping, less debugging.",
        "{name} codes with the intensity of a thousand suns and the efficiency of GAIA's AI. The result? Applications that are both beautiful and bulletproof.",
        "Meet {name}, a developer who believes the best code is the code you don't have to write. With GAIA automating the mundane, they focus on the magic.",
        "{name} is revolutionizing development workflows with GAIA's intelligent automation. Goodbye repetitive tasks, hello creative problem-solving.",
    ],
    "designer": [
        "{name} is a designer who turns pixels into poetry and chaos into creative masterpieces, with GAIA handling everything else. Currently making the world more beautiful, one automated workflow at a time.",
        "Creative genius {name} has unlocked the secret to endless inspiration: let GAIA handle the admin while they handle the aesthetics. Design thinking at the speed of thought.",
        "{name} designs experiences that delight and delegates everything else to GAIA. More creativity, less client emails. More innovation, less iteration management.",
        "Visual virtuoso {name} leverages GAIA to streamline their creative process. From mood boards to final deliverables, they're proving that AI and artistry are perfect partners.",
        "{name} is that designer who always meets deadlines without sacrificing quality, thanks to GAIA's intelligent automation. Making beautiful things beautifully efficient.",
        "Meet {name}, a designer who believes great design needs space to breathe. With GAIA clearing the administrative clutter, creativity flows like never before.",
    ],
    "manager": [
        "{name} is a manager who leads with vision and delegates with GAIA. Transforming team dynamics and crushing KPIs while maintaining legendary work-life balance.",
        "Strategic mastermind {name} uses GAIA to orchestrate operations like a symphony conductor with AI superpowers. Less micromanaging, more macro-impact.",
        "{name} is that manager everyone wants to work for - organized, efficient, and somehow always ahead of schedule. The secret? GAIA handles the chaos while they handle the strategy.",
        "Leadership virtuoso {name} leverages GAIA to transform management from an art into a science. Data-driven decisions, automated reporting, and still time for actual human connection.",
        "{name} manages teams and GAIA manages everything else. The result? Projects that finish on time, budgets that make sense, and teams that actually enjoy Mondays.",
        "Meet {name}, a manager who proves that you can be both liked and respected. With GAIA automating the administrative burden, they focus on what matters: people and progress.",
    ],
    "consultant": [
        "{name} is a consultant who delivers insights at the speed of thought, powered by GAIA's intelligent automation. Turning business problems into success stories, one client at a time.",
        "Strategic advisor {name} combines deep expertise with GAIA's analytical prowess. The result? Recommendations that are both brilliant and actually implementable.",
        "{name} consults by day and lets GAIA handle the data crunching by night. More insights, less spreadsheets. More strategy, less busy work.",
        "Problem-solving virtuoso {name} leverages GAIA to deliver consulting magic. Clients get solutions faster, and {name} gets to actually enjoy weekends.",
        "{name} is that consultant who always has the answer, thanks to GAIA organizing the questions. Transforming businesses with AI-enhanced expertise.",
        "Meet {name}, a consultant who believes in working smarter, not harder. With GAIA automating research and reporting, they focus on what clients really pay for: game-changing insights.",
    ],
    "entrepreneur": [
        "{name} is an entrepreneur who moves fast and breaks things (productively), with GAIA ensuring nothing important actually breaks. Building empires, one automated process at a time.",
        "Visionary founder {name} uses GAIA to run multiple ventures without losing their mind. Scaling businesses at the speed of innovation.",
        "{name} is that entrepreneur who somehow juggles five startups and still makes it to dinner. The secret weapon? GAIA's intelligent automation handling the operational chaos.",
        "Serial innovator {name} leverages GAIA to transform ideas into reality faster than competitors can say 'disruption'. Less admin, more innovation.",
        "{name} builds businesses like they're playing chess - three moves ahead, with GAIA calculating the possibilities. Currently disrupting industries and loving every minute.",
        "Meet {name}, an entrepreneur who believes in failing fast and succeeding faster. With GAIA automating the grind, they focus on the vision.",
        "{name} is revolutionizing entrepreneurship with GAIA's AI assistance. Why have a team of ten when you can have GAIA and achieve the impossible?",
    ],
    "researcher": [
        "{name} is a researcher who discovers breakthroughs before lunch and publishes papers before dinner, thanks to GAIA organizing the infinite complexity of academic life.",
        "Knowledge seeker {name} uses GAIA to navigate the ocean of information and surface with pearls of wisdom. Making discoveries that matter, faster than ever.",
        "{name} researches the unknown and lets GAIA handle the known. More eureka moments, less data entry. More discovery, less documentation drudgery.",
        "Academic innovator {name} leverages GAIA to transform research from a marathon into a sprint. Publishing groundbreaking work while maintaining sanity.",
        "{name} is that researcher who actually has time to think, thanks to GAIA managing citations, data, and deadlines. Pushing the boundaries of human knowledge, efficiently.",
        "Meet {name}, a researcher who believes the best discoveries come from organized minds. With GAIA as their research assistant, breakthrough is always within reach.",
    ],
    "writer": [
        "{name} is a writer who crafts worlds with words and manages reality with GAIA. Currently penning the next masterpiece while AI handles the mundane manuscript management.",
        "Wordsmith extraordinaire {name} has discovered the perfect writing partner: GAIA. Together, they're turning inspiration into publication at unprecedented speed.",
        "{name} writes stories that captivate and lets GAIA handle the plot of daily life. More creativity, less admin. More prose, less process.",
        "Literary virtuoso {name} leverages GAIA to streamline everything from research to revisions. Writer's block? Never heard of it when AI handles the blockers.",
        "{name} is that writer who actually meets deadlines and maintains a muse. The secret? GAIA manages the business while they manage the art.",
        "Meet {name}, a writer who believes great stories need space to breathe. With GAIA clearing the mental clutter, creativity flows like ink on paper.",
    ],
    "artist": [
        "{name} is an artist who paints dreams and sculpts reality, with GAIA ensuring the business side doesn't kill the creative vibe. Making art that matters, minus the starving.",
        "Creative soul {name} uses GAIA to handle galleries, clients, and calendars while they handle the canvas. Finally, an AI that understands artists need space to create.",
        "{name} creates masterpieces and GAIA creates order from the creative chaos. More inspiration, less administration. More studio time, less screen time.",
        "Visionary artist {name} leverages GAIA to transform artistic passion into sustainable practice. Proving that creatives can be both inspired and organized.",
        "{name} is that artist who actually makes a living from their art, thanks to GAIA managing the business side. Living the dream, creating the extraordinary.",
        "Meet {name}, an artist who believes creativity shouldn't be constrained by logistics. With GAIA as their assistant, art becomes the only priority.",
    ],
    "doctor": [
        "{name} is a doctor who heals bodies and minds while GAIA heals their schedule. Practicing medicine at the highest level without the administrative headaches.",
        "Medical virtuoso {name} uses GAIA to manage the complexity of modern healthcare. More patient time, less paperwork. More healing, less filing.",
        "{name} saves lives by day and lets GAIA save their sanity by night. Revolutionizing patient care with AI-powered efficiency.",
        "Healthcare hero {name} leverages GAIA to balance patient care with personal care. Finally, a doctor who has time to take their own advice about work-life balance.",
        "{name} is that doctor who remembers every patient's name and still makes it home for dinner. The prescription? GAIA's intelligent automation.",
        "Meet {name}, a doctor who believes healing requires focus. With GAIA handling the administrative load, they concentrate on what matters: patients.",
    ],
    "lawyer": [
        "{name} is a lawyer who wins cases and lets GAIA handle the case files. Practicing law at the speed of justice, not at the pace of paperwork.",
        "Legal eagle {name} uses GAIA to navigate the labyrinth of law with AI-powered precision. More strategy, less discovery. More advocacy, less administration.",
        "{name} argues brilliantly in court and delegates brilliantly to GAIA. The result? Justice served hot and invoices served on time.",
        "Legal virtuoso {name} leverages GAIA to transform law practice from grinding to thriving. Billable hours up, actual hours down.",
        "{name} is that lawyer who actually reads every document and still has weekends. The secret? GAIA handles the routine while they handle the remarkable.",
        "Meet {name}, a lawyer who believes justice shouldn't wait for paperwork. With GAIA automating the mundane, they focus on making a difference.",
    ],
    "accountant": [
        "{name} is an accountant who makes numbers dance and lets GAIA handle the music. Transforming financial chaos into strategic clarity, one automated report at a time.",
        "Numbers ninja {name} uses GAIA to turn spreadsheet slavery into financial freedom. More analysis, less data entry. More insights, less overtime.",
        "{name} balances books and life with equal precision, thanks to GAIA's intelligent automation. Finally, an accountant who doesn't live in Excel.",
        "Financial virtuoso {name} leverages GAIA to deliver insights that actually drive decisions. Making CFOs happy and somehow still enjoying tax season.",
        "{name} is that accountant who finds errors before they become problems, with GAIA scanning every transaction. Precision meets efficiency meets weekend plans.",
        "Meet {name}, an accountant who believes numbers tell stories. With GAIA handling the calculations, they focus on the narrative.",
    ],
    "sales": [
        "{name} is a sales dynamo who closes deals and lets GAIA close the loops. Crushing quotas while maintaining authentic relationships and actual free time.",
        "Revenue rockstar {name} uses GAIA to transform cold calls into hot leads and prospects into partners. Selling smarter, not harder.",
        "{name} sells solutions by day and lets GAIA solve the CRM nightmare by night. More conversations, less data entry. More commissions, less confusion.",
        "Sales virtuoso {name} leverages GAIA to turn the sales funnel into a sales rocket. Pipeline management has never been this smooth.",
        "{name} is that salesperson who remembers every client's birthday and still beats quota by 200%. The advantage? GAIA's intelligent relationship management.",
        "Meet {name}, a sales professional who believes in relationships over transactions. With GAIA handling the process, they focus on the people.",
        "{name} is revolutionizing sales with GAIA's AI assistance. Why chase leads when you can attract them with intelligent automation?",
    ],
    "marketing": [
        "{name} is a marketing maestro who creates campaigns that convert and lets GAIA handle the metrics madness. Building brands at the speed of viral.",
        "Creative strategist {name} uses GAIA to transform marketing from guesswork into science. More creativity, less spreadsheets. More impact, less busywork.",
        "{name} markets like a magician and measures like a mathematician, with GAIA bridging the creative-analytical divide. ROI has never looked so good.",
        "Marketing virtuoso {name} leverages GAIA to orchestrate omnichannel campaigns without losing their mind. Finally, marketing automation that actually works.",
        "{name} is that marketer who launches campaigns that trend and still makes happy hour. The secret? GAIA handles execution while they handle strategy.",
        "Meet {name}, a marketer who believes great campaigns need both art and science. With GAIA crunching numbers, they're free to craft narratives.",
    ],
    "analyst": [
        "{name} is an analyst who finds patterns in chaos and insights in noise, with GAIA amplifying their analytical superpowers. Turning data into decisions at unprecedented speed.",
        "Data detective {name} uses GAIA to solve business mysteries before lunch and predict the future after. Making sense of complexity, one dataset at a time.",
        "{name} analyzes like a supercomputer thinks, with GAIA handling the heavy lifting. More insights, less Excel. More strategy, less struggle.",
        "Analytical virtuoso {name} leverages GAIA to transform information overload into competitive advantage. Finding needles in haystacks is just another Tuesday.",
        "{name} is that analyst whose reports actually get read and acted upon. Why? Because GAIA handles the boring parts while they focus on the story.",
        "Meet {name}, an analyst who believes data without insight is just noise. With GAIA automating the analysis, they focus on the implications.",
    ],
    "freelancer": [
        "{name} is a freelancer who juggles clients like a circus performer and manages projects like a CEO, all thanks to GAIA's intelligent automation. Freedom never felt so organized.",
        "Independent powerhouse {name} uses GAIA to run a one-person empire. Multiple clients, zero chaos. Maximum freedom, minimum stress.",
        "{name} freelances with the efficiency of an agency and the agility of a solo act. GAIA handles the admin so they can handle the awesome.",
        "Freelance virtuoso {name} leverages GAIA to deliver agency-quality work with indie-spirit freedom. Clients love the results, {name} loves the lifestyle.",
        "{name} is that freelancer who never misses deadlines and still takes vacations. The hack? GAIA manages the business while they manage the craft.",
        "Meet {name}, a freelancer who believes independence shouldn't mean isolation. With GAIA as their virtual team, they're unstoppable.",
        "{name} is redefining freelance life with GAIA's AI assistance. Why choose between freedom and success when you can automate your way to both?",
    ],
    "retired": [
        "{name} is living their best retirement life, with GAIA ensuring the golden years are actually golden. Finally, someone who retired from work, not from living.",
        "Wisdom keeper {name} uses GAIA to stay connected, engaged, and ahead of the technology curve. Proving that retirement is just the beginning of the adventure.",
        "{name} retired from the grind but not from the game. With GAIA handling the digital complexities, they're free to focus on what matters: living fully.",
        "Life enthusiast {name} leverages GAIA to manage investments, hobbies, and grandkid schedules with ease. Retirement reimagined with AI assistance.",
        "{name} is that retiree who's busier than ever, but it's all joy, no stress. GAIA handles the logistics while they handle the bucket list.",
        "Meet {name}, proof that retirement can be both relaxing and productive. With GAIA as their digital assistant, every day is optimized for enjoyment.",
    ],
    "other": [
        "{name} defies conventional categories and so does their approach to productivity. With GAIA's intelligent automation, they're writing their own success story.",
        "Unique individual {name} uses GAIA to craft a life that doesn't fit in boxes. Automating the ordinary to focus on the extraordinary.",
        "{name} is charting their own course with GAIA as their navigator. Whatever the goal, AI-powered assistance makes the journey smoother.",
        "Unconventional thinker {name} leverages GAIA to turn ambitious dreams into daily reality. No label needed when you're this efficient.",
        "{name} is exploring GAIA's intelligent automation capabilities to transform daily workflows and unlock new levels of productivity. Ready to harness the power of personalized AI assistance.",
        "Meet {name}, someone who believes productivity isn't one-size-fits-all. With GAIA adapting to their unique needs, anything is possible.",
        "{name} is revolutionizing their personal and professional life with GAIA's versatile AI assistance. Categories are limiting, potential is not.",
    ],
}


def get_random_bio_for_profession(name: str, profession: str) -> str:
    """
    Get a random bio for a given profession.

    Args:
        name: User's name to insert into the bio
        profession: The profession key (lowercase)

    Returns:
        A formatted bio string with the user's name
    """
    # Normalize profession to lowercase
    profession = profession.lower().strip()

    # Get bios for the profession, or use 'other' as fallback
    bios = PROFESSION_BIOS.get(profession, PROFESSION_BIOS["other"])

    # Select a random bio and format with the name
    selected_bio = random.choice(bios)  # nosec: B311
    return selected_bio.format(name=name)


def get_all_professions() -> Tuple[str, ...]:
    """Get tuple of all available professions."""
    return PROFESSIONS


def validate_profession(profession: str) -> bool:
    """Check if a profession is in our predefined list."""
    return profession.lower().strip() in PROFESSIONS
