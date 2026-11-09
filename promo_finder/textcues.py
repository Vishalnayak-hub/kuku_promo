"""Small, explicit text cues used by the heuristic judge.

Everything here is a *documented guess*, not a trained model. Keeping the
lexicons short and readable is deliberate: an editor can read them, argue with
them, and change them. The LLM judge (``llm.py``) is the semantic layer; these
cues are the cheap, offline, free first pass that also decides which windows
are worth sending to a model.
"""
from __future__ import annotations

import re

from .models import Event

# --- delivery tags written by the screenwriter: "(Cold, Commanding)" ---------
# v1 parsed these and then threw them away. They are the richest emotion signal
# in the pack: 100 % of dialogue lines carry 1-3 of them.
HIGH_AROUSAL = {
    "shouting", "screaming", "furious", "enraged", "outraged", "desperate", "panicked",
    "terrified", "horrified", "threatening", "venomous", "aggressive", "snarl", "snarling",
    "hysterical", "sobbing", "wailing", "roaring", "explosive", "savage", "frantic",
    "livid", "vicious", "seething", "anguished", "agonized", "shrieking", "yelling",
    "menacing", "murderous", "frenzied", "devastated", "stricken", "gasping",
}
MED_AROUSAL = {
    "urgent", "pleading", "defiant", "cold", "fierce", "stern", "sharp", "mocking",
    "scornful", "cruel", "trembling", "breathless", "weeping", "tearful", "accusatory",
    "demanding", "commanding", "authoritative", "smug", "gloating", "taunting", "ominous",
    "grave", "steely", "shocked", "startled", "incredulous", "stunned", "indignant",
    "contemptuous", "sinister", "provoking", "haunted", "anguish", "pained", "heartbroken",
    "distressed", "alarmed", "dark", "grated", "scoffing", "disdainful", "condescending",
    "crying", "dramatic", "whispering", "bitter", "resentful", "suspicious", "ruthless",
}
LOW_AROUSAL = {
    "gentle", "soft", "calm", "quiet", "warm", "tender", "reassuring", "sincere", "relieved",
    "grateful", "content", "peaceful", "affectionate", "loving", "soothing", "kind",
    "hopeful", "relaxed", "serene", "polite", "cheerful", "joyful", "happy", "light",
}
DEFAULT_INTENSITY = 0.35


def tag_intensity(tags: tuple[str, ...]) -> float:
    if not tags:
        return DEFAULT_INTENSITY
    best = 0.0
    for t in tags:
        for word in re.split(r"[\s/-]+", t):
            if word in HIGH_AROUSAL:
                best = max(best, 1.0)
            elif word in MED_AROUSAL:
                best = max(best, 0.6)
            elif word in LOW_AROUSAL:
                best = max(best, 0.15)
    return best if best > 0 else DEFAULT_INTENSITY


def line_intensity(d: Event) -> float:
    value = tag_intensity(d.tags)
    if "!" in d.text:
        value = min(1.0, value + 0.12)
    return value


# --- sentence-shape cues -----------------------------------------------------
_CLOSERS = "\"'\u201d\u2019) "


def ends_with_question(text: str) -> bool:
    return text.rstrip(_CLOSERS).endswith("?")


def ends_interrupted(text: str) -> bool:
    t = text.rstrip(_CLOSERS)
    return t.endswith(("\u2014", "--", "\u2026", "...")) or (t.endswith("-") and not t.endswith(" -"))


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


IMPERATIVE = re.compile(
    r"^\W*(stop|wait|don'?t|do not|get out|get away|get back|leave|let (?:go|her|him|them)|"
    r"release|look at me|listen|answer me|say it|tell me|how dare|enough|run|help|no[!,.]|"
    r"never|bring|seize|arrest|take (?:her|him|them)|guards?|open|put it|give me|step back|"
    r"kneel|silence|out of my|hands off|move)\b", re.I)

ULTIMATUM = re.compile(
    r"\b(or else|or I will|you will (?:pay|regret|never|die|burn)|I will (?:kill|destroy|ruin|"
    r"make you|see you|have you|never)|you are (?:under|dead|finished|done)|you(?:'re| are) "
    r"(?:not|no longer)|get out|never (?:again|forgive)|last chance|one more (?:word|step)|"
    r"I swear|on pain of|by the end of)\b", re.I)

REVEAL = re.compile(
    r"\b(secret|truth|lied|liar|lie[sd]?|never told|all along|didn'?t know|real name|"
    r"true identity|who are you|what have you done|you(?:'re| are) (?:my|the|her|his)|"
    r"your (?:mother|father|brother|sister|real)|pregnant|alive|dead|married|betray(?:ed|al)?|"
    r"poison(?:ed|ing)?|murder(?:ed|er)?|thief|traitor|impostor|witch|heir|bastard|"
    r"i am (?:the|her|his|your)|it was (?:you|me|him|her)|planted|framed|confess)\b", re.I)

CONFLICT = re.compile(
    r"\b(accus\w*|thief|steal|stole|stolen|lie[sd]?|liar|traitor|betray\w*|guilty|innocent|"
    r"arrest\w*|poison\w*|kill\w*|murder\w*|dead|die|death|curse\w*|witch\w*|prison|dungeon|"
    r"whip|brand\w*|punish\w*|destroy\w*|ruin\w*|reveng\w*|vengeance|threat\w*|forbid\w*|"
    r"forbidden|blood|scandal|disgrace\w*|shame\w*|seiz\w*|frame[ds]?|planted|trial|"
    r"execut\w*|banish\w*|beg|plead\w*)\b", re.I)

CLOSURE = re.compile(
    r"^\W*(thank you|thanks|goodbye|farewell|good night|good morning|very well|as you wish|"
    r"i understand|of course|yes[,.! ]|yes$|alright|all right|it is done|i promise|"
    r"i love you|i forgive|i accept|i agree|you are right|forgive me|bless you|amen|"
    r"welcome home|rest now|sleep now|peace)", re.I)

WEAK_OPENER = re.compile(
    r"^\W*(good (?:morning|evening|day|night)|hello|hi\b|welcome|thank you|thanks|please sit|"
    r"how are you|i hope|forgive the|my lady,? (?:i|it)|as you know)", re.I)
DISCOURSE_OPENER = re.compile(r"^\W*(and|but|so|then|because|well|yet|also|though|anyway)\b", re.I)
PRONOUN_OPENER = re.compile(r"^\W*(him|her|them|it|that|this|those|these|he|she|they)\b", re.I)

# Openings that often depend on information from an earlier exchange.
# These are contextual warning signals, not automatic proof of a weak hook.
CONTEXT_DEPENDENT_OPENER = re.compile(
    r"^\W*("
    r"what about (?:him|her|them|it|that|this)|"
    r"where (?:is|was|are|were) (?:he|she|they|it|that|the man|the woman)|"
    r"why (?:did|does|would|has|have) you|"
    r"how (?:could|can|did|would) you|"
    r"when (?:did|will|has|does) (?:he|she|they|it)|"
    r"which one|"
    r"the same (?:man|woman|thing|person)|"
    r"what happened to (?:him|her|them|it)|"
    r"do it again|"
    r"as I said|like I told you"
    r")\b",
    re.I,
)

# words in ACTION / SOUND_FX text
IMPACT_ACTION = re.compile(
    r"\b(slap\w*|strik\w*|struck|shov\w*|drag\w*|throw\w*|threw|hurl\w*|grab\w*|seiz\w*|slam\w*|"
    r"burst\w*|collaps\w*|shatter\w*|smash\w*|stagger\w*|punch\w*|kick\w*|pull\w* (?:a |out |her |his )?"
    r"(?:sword|dagger|blade|pistol|knife)|draw\w* (?:a |his |her )?(?:sword|dagger|blade|pistol|knife)|"
    r"rais\w* (?:a |his |her )?(?:sword|dagger|blade|whip|fist|hand to strike)|brand\w*|whip\w*|"
    r"faint\w*|fall\w* (?:to|onto|back)|drop\w* (?:to|the)|kneel\w*|rip\w*|tear\w* (?:off|open)|"
    r"spit\w*|push\w*|restrain\w*|chok\w*|stab\w*|shot|fires?)\b", re.I)

SUDDEN_END = re.compile(
    r"\b(door (?:opens|swings|bursts|slams|creak\w*)|knock\w*|enters?|appears?|steps? (?:in|out|forward)|"
    r"reveal\w*|discover\w*|gasp\w*|scream\w*|shriek\w*|crash\w*|shatter\w*|slam\w*|gunshot|shot|"
    r"thunder\w*|bell|footsteps|stormed?|bursts?|collaps\w*|falls?|freez\w*|horror|shock\w*|"
    r"stunned|silence|stares?|frozen|drops?|pulls? (?:out|from)|holds? up|unveil\w*|"
    r"lunges?|rushes?|alarm|cry out|cries out)\b", re.I)


def has_closure(text: str) -> bool:
    return bool(CLOSURE.search(text.strip()))


# camera text is the only visual information in the pack; keep this list narrow so that
# ordinary shot descriptions ("close-up of her face") do not count as a reveal
VISUAL_REVEAL = re.compile(
    r"\b(reveal\w*|discover\w*|appears?|emerg\w*|enters?|door (?:opens|swings|bursts)|"
    r"swings? open|bursts? (?:in|open|through)|collaps\w*|shatter\w*|slam\w*|pulls? (?:out|from)|"
    r"holds? up|unveil\w*|lunges?|stormed?|stands? (?:in|at) the doorway|figure|intruder)\b", re.I)
