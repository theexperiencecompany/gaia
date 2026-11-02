"""The welcome thread's fixed copy, one table per language the web app ships in.

Keyed by the primary language subtag stored on OnboardingPreferences.language.
A language without a table gets English: a stranger's greeting in the wrong
language reads worse than a plain one in English.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WelcomeCopy:
    """Every fixed string of the welcome thread, in one language."""

    welcome: str
    handover_line: str
    #: Appended to handover_line, so it carries its own leading space where the language needs one.
    platform_template: str
    routines_intro: str
    gmail_line: str
    calendar_line: str
    connect_gmail: str
    connect_calendar: str
    all_integrations: str
    whats_first: str
    something_else: str


DEFAULT_LANGUAGE = "en"

WELCOME_COPY: dict[str, WelcomeCopy] = {
    "en": WelcomeCopy(
        welcome="Okay, you're in.",
        handover_line="Anything you'd rather not do yourself, hand it to me.",
        platform_template=" I'm on your {platform} too.",
        routines_intro="Two things worth switching on now.",
        gmail_line="Gmail: every morning your mail comes back sorted, replies drafted.",
        calendar_line="Calendar: I brief you before every meeting.",
        connect_gmail="Connect Gmail",
        connect_calendar="Connect Calendar",
        all_integrations="All integrations",
        whats_first="What's first?",
        something_else="Something else",
    ),
    "es": WelcomeCopy(
        welcome="Listo, ya estás dentro.",
        handover_line="Lo que prefieras no hacer tú, pásamelo.",
        platform_template=" También estoy en tu {platform}.",
        routines_intro="Dos cosas que vale la pena activar ya.",
        gmail_line="Gmail: cada mañana tu correo llega ordenado, con las respuestas en borrador.",
        calendar_line="Calendar: te preparo antes de cada reunión.",
        connect_gmail="Conectar Gmail",
        connect_calendar="Conectar Calendar",
        all_integrations="Todas las integraciones",
        whats_first="¿Por dónde empezamos?",
        something_else="Otra cosa",
    ),
    "fr": WelcomeCopy(
        welcome="Voilà, c'est parti.",
        handover_line="Tout ce que tu préfères ne pas faire toi-même, confie-le-moi.",
        platform_template=" Je suis aussi sur ton {platform}.",
        routines_intro="Deux choses à activer dès maintenant.",
        gmail_line="Gmail : chaque matin, tes mails arrivent triés, avec les réponses en brouillon.",
        calendar_line="Agenda : je te briefe avant chaque réunion.",
        connect_gmail="Connecter Gmail",
        connect_calendar="Connecter l'agenda",
        all_integrations="Toutes les intégrations",
        whats_first="On commence par quoi ?",
        something_else="Autre chose",
    ),
    "de": WelcomeCopy(
        welcome="So, du bist drin.",
        handover_line="Alles, was du lieber nicht selbst machst, gib es mir.",
        platform_template=" Ich bin auch auf deinem {platform}.",
        routines_intro="Zwei Dinge, die sich jetzt lohnen.",
        gmail_line="Gmail: Jeden Morgen kommt deine Mail sortiert zurück, Antworten schon entworfen.",
        calendar_line="Kalender: Vor jedem Meeting bekommst du ein Briefing von mir.",
        connect_gmail="Gmail verbinden",
        connect_calendar="Kalender verbinden",
        all_integrations="Alle Integrationen",
        whats_first="Womit fangen wir an?",
        something_else="Etwas anderes",
    ),
    "pt": WelcomeCopy(
        welcome="Pronto, você está dentro.",
        handover_line="O que você preferir não fazer, deixa comigo.",
        platform_template=" Também estou no seu {platform}.",
        routines_intro="Duas coisas que valem a pena ativar agora.",
        gmail_line="Gmail: toda manhã seus e-mails chegam organizados, com as respostas em rascunho.",
        calendar_line="Agenda: eu te preparo antes de cada reunião.",
        connect_gmail="Conectar Gmail",
        connect_calendar="Conectar Agenda",
        all_integrations="Todas as integrações",
        whats_first="Por onde começamos?",
        something_else="Outra coisa",
    ),
    "ja": WelcomeCopy(
        welcome="準備できました。",
        handover_line="自分でやりたくないことは、私に任せてください。",
        platform_template="{platform}でも連絡できます。",
        routines_intro="今すぐオンにしておきたいものが2つあります。",
        gmail_line="Gmail：毎朝メールを整理して、返信の下書きまで用意します。",
        calendar_line="カレンダー：会議の前に毎回ブリーフィングします。",
        connect_gmail="Gmailを接続",
        connect_calendar="カレンダーを接続",
        all_integrations="すべての連携",
        whats_first="何から始めますか？",
        something_else="その他",
    ),
    "ko": WelcomeCopy(
        welcome="자, 시작할게요.",
        handover_line="직접 하기 싫은 일은 저에게 맡기세요.",
        platform_template=" {platform}에서도 만날 수 있어요.",
        routines_intro="지금 켜두면 좋은 두 가지가 있어요.",
        gmail_line="Gmail: 매일 아침 메일을 정리하고 답장 초안까지 준비해요.",
        calendar_line="캘린더: 회의 전마다 브리핑해 드려요.",
        connect_gmail="Gmail 연결",
        connect_calendar="캘린더 연결",
        all_integrations="모든 연동",
        whats_first="무엇부터 할까요?",
        something_else="다른 것",
    ),
}


def welcome_copy(language: str | None) -> WelcomeCopy:
    """Return the copy for language, or English when there is no table for it."""
    return WELCOME_COPY.get(language or DEFAULT_LANGUAGE, WELCOME_COPY[DEFAULT_LANGUAGE])
