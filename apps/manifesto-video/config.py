# apps/manifesto-video/config.py
from pathlib import Path

ROOT = Path(__file__).parent

CLIPS_RAW     = ROOT / "clips" / "raw"
CLIPS_TRIMMED = ROOT / "clips" / "trimmed"
OUTPUT        = ROOT / "output"
MUSIC_FILE    = ROOT / "music" / "track.mp3"

# ---------------------------------------------------------------------------
# CLIP MANIFEST  (order = order in final video)
# ---------------------------------------------------------------------------
CLIPS = [
    {
        "id": "apollo_control",
        "url": "https://archive.org/download/76494NASALaunchOfSaturnV/76494%20NASA%20Launch%20Of%20Saturn%20V.mp4",
        "start": "00:02:55",
        "duration": 3,
        "desc": "Saturn V rocket launch — engines firing, liftoff",
    },
    {
        "id": "einstein",
        "url": "https://ia600303.us.archive.org/0/items/capsca_00009/capsca_00009_access.HD.mp4",
        "start": "00:01:20",
        "duration": 3,
        "desc": "Einstein at Caltech — face visible, candid 1932 footage",
    },
    {
        "id": "jfk_moon",
        "url": "https://archive.org/download/nasa_tv-JFK_s_Rice_Speech_on_NASA_TV_Sept._12/JFK_s_Rice_Speech_on_NASA_TV_Sept._12.mp4",
        "start": "00:00:30",
        "duration": 3,
        "desc": "JFK Rice University — We choose to go to the moon",
    },
    {
        "id": "mlk_speech",
        "url": "https://archive.org/download/youtube-1UV1fs8lAbg/1UV1fs8lAbg.mp4",
        "start": "00:12:30",
        "duration": 3,
        "desc": "MLK I Have a Dream — the iconic delivery, 1963",
    },
    {
        "id": "ali_fight",
        "url": "https://archive.org/download/MuhammadAliVsSonnyListon/MuhammadAliVsSonnyListon_512kb.mp4",
        "start": "00:10:00",
        "duration": 3,
        "desc": "Muhammad Ali — Liston on canvas, phantom punch KO 1965",
    },
    {
        "id": "earth_orbit",
        "url": "https://archive.org/download/Time-lapseAstronautPhotographyOfEarth-2/TimeLapse_HalfwayAcross.mp4",
        "start": "00:00:01",
        "duration": 3,
        "desc": "ISS time-lapse — Earth from orbit",
    },
    {
        "id": "jobs_iphone",
        "url": "https://archive.org/download/i-phone-1-steve-jobs-mac-world-keynote-in-2007-full-presentation-80-mins/iPhone%201%20-%20Steve%20Jobs%20MacWorld%20keynote%20in%202007%20-%20Full%20Presentation%2C%2080%20mins.ia.mp4",
        "start": "00:05:50",
        "duration": 4,
        "desc": "Jobs — An iPod, a phone, and an internet communicator (the 3 things reveal)",
    },
    {
        "id": "feynman",
        "url": "https://archive.org/download/FunToImagine/Richard%20P%20Feynman%20-%20FUN%20TO%20IMAGINE%20(full).mp4",
        "start": "00:03:00",
        "duration": 3,
        "desc": "Feynman mid-explanation — total absorption in thought",
    },
    {
        "id": "carlsen_chess",
        "url": "https://archive.org/download/youtube-oiea--ra5as/oiea--ra5as.mp4",
        "start": "00:01:00",
        "duration": 3,
        "desc": "Magnus Carlsen vs Keymer, World Blitz 2022 — over-the-board",
    },
    {
        "id": "michael_jackson",
        "url": "https://archive.org/download/michael-jackson-billie-jean-1983-motown-25-live/Michael%20Jackson%20-%20Billie%20Jean%20%5B1983%20Motown%2025%20Live%5D.mp4",
        "start": "00:03:15",
        "duration": 3,
        "desc": "Michael Jackson — moonwalk debut, Motown 25 1983",
    },
    {
        "id": "pele",
        "url": "https://archive.org/download/1970-fifa-world-cup-final-brazil-italy/1970%20FIFA%20World%20Cup%20Final_Brazil-Italy.mp4",
        "start": "00:18:00",
        "duration": 3,
        "desc": "Pelé — 1970 World Cup Final, Brazil vs Italy",
    },
    {
        "id": "maradona",
        "url": "https://archive.org/download/2331687-maradona-onderstreept-zijn-status-met-prachtige-sologoal-op-wk-86/2331687-maradona-onderstreept-zijn-status-met-prachtige-sologoal-op-wk-86.mp4",
        "start": "00:00:15",
        "duration": 4,
        "desc": "Maradona — Goal of the Century, 1986 World Cup",
    },
    {
        "id": "bolt_sprint",
        "url": "https://archive.org/download/UsainBoltWinsOlympic100mGoldLondon2012Olympics/Usain%20Bolt%20Wins%20Olympic%20100m%20Gold%20-%20London%202012%20Olympics.mp4",
        "start": "00:06:30",
        "duration": 3,
        "desc": "Usain Bolt — London 2012 Olympic 100m gold",
    },
    {
        "id": "federer",
        "url": "https://archive.org/download/2018-roger-federer-v.-novak-djokovic-2018-cincinnati-f-highlights/2018%20-%20Roger%20Federer%20v.%20Novak%20Djokovic%20%7C%202018%20Cincinnati%20F%20Highlights.mp4",
        "start": "00:03:00",
        "duration": 3,
        "desc": "Roger Federer — Cincinnati 2018 final highlights",
    },
    {
        "id": "bruce_lee",
        "url": "https://archive.org/download/bruce-lee-a-warriors-journey/Bruce%20Lee%20A%20Warriors%20Journey%20%282000%29.ia.mp4",
        "start": "01:15:00",
        "duration": 3,
        "desc": "Bruce Lee — Game of Death fight footage at full speed",
    },
    {
        "id": "armstrong_moon",
        "url": "https://archive.org/download/apollo-11-mission/Apollo%2011%2010.mp4",
        "start": "01:00:00",
        "duration": 3,
        "desc": "Neil Armstrong — Apollo 11 EVA, lunar module on moon surface",
    },
    {
        "id": "city_night",
        "url": "https://archive.org/download/pixabay-21985/video-21985_large.mp4",
        "start": "00:00:00",
        "duration": 4,
        "desc": "Seoul city night — noise, lights, chaos",
    },
    {
        "id": "earth_orbit_2",
        "url": "https://archive.org/download/Time-lapseAstronautPhotographyOfEarth-2/TimeLapse_HalfwayAcross.mp4",
        "start": "00:00:14",
        "duration": 4,
        "desc": "Earth from orbit — second pass, vast and quiet",
    },
    # gaia_black: 9s black end card, generated by assemble.py
]

# ---------------------------------------------------------------------------
# CLIP BOUNDARIES (cumulative seconds) — for reference when editing TEXT_TIMELINE
#   [0–3]    apollo_control     (Saturn V launch)
#   [3–6]    einstein
#   [6–9]    jfk_moon
#   [9–12]   mlk_speech
#   [12–15]  ali_fight          (silent — Liston KO)
#   [15–18]  earth_orbit        (3s — silent beat)
#   [18–22]  jobs_iphone        (4s — 3 things reveal)
#   [22–25]  feynman
#   [25–28]  carlsen_chess
#   [28–31]  michael_jackson
#   [31–34]  pele               (1970 World Cup Final)
#   [34–38]  maradona           (4s — silent)
#   [38–41]  bolt_sprint
#   [41–44]  federer
#   [44–47]  bruce_lee          (silent)
#   [47–50]  armstrong_moon
#   [50–54]  city_night         (4s)
#   [54–58]  earth_orbit_2      (4s)
#   [58–67]  gaia_black         (9s)
# ---------------------------------------------------------------------------
TEXT_TIMELINE = [
    # [0.5–2.5]
    {"time": 0.5,  "dur": 2.0, "text": "The work that matters"},
    # [3.3–5.5]
    {"time": 3.3,  "dur": 2.2, "text": "doesn\u2019t happen in meetings."},
    # [6.3–8.4]  over jfk_moon
    {"time": 6.3,  "dur": 2.1, "text": "It happens in the hours"},
    # [9.3–11.4]  over mlk_speech
    {"time": 9.3,  "dur": 2.1, "text": "when the world goes quiet."},
    # ali_fight [12–15] silent, earth_orbit [15–18] silent
    # [18.3–20.2]  over jobs_iphone
    {"time": 18.3, "dur": 1.9, "text": "Every person"},
    # [21.3–23.4]  jobs/feynman
    {"time": 21.3, "dur": 2.1, "text": "who ever changed anything"},
    # [24.3–26.3]  feynman/carlsen
    {"time": 24.3, "dur": 2.0, "text": "protected those hours."},
    # [27.5–29.1]  carlsen/mj
    {"time": 27.5, "dur": 1.6, "text": "Fiercely."},
    # pele [31–34] silent, maradona [34–38] silent
    # [38.3–40.0]  over bolt_sprint
    {"time": 38.3, "dur": 1.7, "text": "Not talent."},
    # [41.3–42.8]  over federer
    {"time": 41.3, "dur": 1.5, "text": "Hours."},
    # bruce_lee [44–47] silent
    # [47.5–49.8]  over armstrong_moon
    {"time": 47.5, "dur": 2.3, "text": "They weren\u2019t more talented than you."},
    # [50.5–53.3]  over city_night
    {"time": 50.5, "dur": 2.8, "text": "The world got louder."},
    # [54.2–56.8]  over earth_orbit_2
    {"time": 54.2, "dur": 2.6, "text": "Yours doesn\u2019t have to."},
    # [60.0–62.5]  gaia_black — let black breathe first
    {"time": 60.0, "dur": 2.5, "text": "GAIA"},
    # [63.5–66.5]  gaia_black
    {"time": 63.5, "dur": 3.0, "text": "Do the work."},
]

# ---------------------------------------------------------------------------
# VIDEO SETTINGS
# ---------------------------------------------------------------------------
FPS              = 30
VIDEO_W          = 1920
VIDEO_H          = 1080
MUSIC_VOLUME     = 0.6
MUSIC_FADE_START = 56   # seconds — music fades out during earth_orbit_2, silent for GAIA

# Cinematic grade: desaturated, high contrast, crushed blacks
COLOR_GRADE = (
    "eq=contrast=1.25:brightness=-0.06:saturation=0.65,"
    "curves=r='0/0 0.45/0.38 1/0.88':g='0/0 0.45/0.38 1/0.88':b='0/0 0.45/0.42 1/1.0'"
)

# Text — Helvetica Neue Medium Italic, yellow, black outline
FONT_FILE    = str(ROOT / "fonts" / "HelveticaNeue-MediumItalic.ttf")
FONT_SIZE    = 60
FONT_COLOR   = "#FFE033"
BORDER_COLOR = "black"
BORDER_W     = 4
TEXT_X       = "(w-text_w)/2"
TEXT_Y       = "(h*0.82)"
