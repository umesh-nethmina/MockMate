"""Speech metrics tool (FR-43): filler words, words per minute and answer length for spoken answers.

Deterministic and cheap, so the orchestrator calls it directly instead of spending an LLM call on it.
Metrics are computed from the raw speech-to-text transcript, before the candidate edits it (FR-23),
so tidying the text does not hide fillers. Note that browser speech recognition often drops "um"/"uh",
so filler counts are a lower bound.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

# Sounds that are always fillers
_HESITATIONS = r"u+m+|u+h+|e+r+m*|a+h+|h+m+"
# Hedge words that are almost always fillers in spoken answers
_HEDGES = r"basically|actually|literally"
# "you know" / "I mean" used as fillers (not "do you know", "what I mean is")
_PHRASES = (
    r"(?<!do )(?<!did )you know(?! (?:how|what|why|when|where|that|the|a|about|if))"
    r"|(?<!what )i mean(?! (?:that|to|it))"
)
# "like" as a filler: not after words that make it a verb or comparison ("I like", "would like", "looks like")
_LIKE = (
    r"(?<!\bi )(?<!\byou )(?<!\bwe )(?<!\bthey )(?<!\bwould )(?<!\bd )(?<!\bdon't )(?<!\bdidn't )"
    r"(?<!\breally )(?<!\blooks )(?<!\blook )(?<!\bseems )(?<!\bfeel )(?<!\bfeels )(?<!\bsomething )"
    r"(?<!\bjust )(?<!\bmore )(?<!\bthings )like(?! to\b)"
)
# "kind of" / "sort of" as hedges, not "what kind of database"
_KIND_OF = (
    r"(?<!\bwhat )(?<!\bwhich )(?<!\bthis )(?<!\bthat )(?<!\bthe )(?<!\ba )"
    r"(?<!\bany )(?<!\bsome )(?<!\bevery )(?<!\bsame )(?:kind|sort) of"
)

FILLER_RE = re.compile(rf"\b(?:{_HESITATIONS}|{_HEDGES}|{_PHRASES}|{_LIKE}|{_KIND_OF})\b", re.IGNORECASE)
WORD_RE = re.compile(r"[A-Za-z0-9']+")

MIN_SECONDS_FOR_WPM = 3.0
IDEAL_WPM = (110, 160)


@dataclass
class SpeechMetrics:
    word_count: int
    wpm: float | None
    filler_count: int
    filler_words: dict[str, int] = field(default_factory=dict)


def _normalise(word: str) -> str:
    w = word.lower()
    for pattern, label in ((r"u+m+", "um"), (r"u+h+", "uh"), (r"e+r+m*", "er"), (r"a+h+", "ah"), (r"h+m+", "hmm")):
        if re.fullmatch(pattern, w):
            return label
    return re.sub(r"\s+", " ", w)


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def analyse(transcript: str, speech_seconds: float | None) -> SpeechMetrics:
    words = word_count(transcript)
    counts = Counter(_normalise(m.group(0)) for m in FILLER_RE.finditer(transcript))
    wpm = None
    if speech_seconds and speech_seconds >= MIN_SECONDS_FOR_WPM and words:
        wpm = round(words / (speech_seconds / 60), 1)
    return SpeechMetrics(
        word_count=words,
        wpm=wpm,
        filler_count=sum(counts.values()),
        filler_words=dict(counts.most_common()),
    )


def pace_label(wpm: float | None) -> str | None:
    if wpm is None:
        return None
    low, high = IDEAL_WPM
    if wpm < low:
        return "slow"
    if wpm > high:
        return "fast"
    return "good"
