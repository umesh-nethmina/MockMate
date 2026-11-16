import pytest

from app.models import Message
from app.tools.speech_metrics import analyse, pace_label, word_count

SETUP = {"role": "Python developer", "level": "junior", "session_type": "technical", "question_limit": 3}


# ---------- speech metrics tool ----------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Um, so basically I, uh, built like a chess engine", {"um": 1, "basically": 1, "uh": 1, "like": 1}),
        ("Ummm I think, erm, it was, you know, kind of slow", {"um": 1, "er": 1, "you know": 1, "kind of": 1}),
        ("I like Python and would like to join. It looks like a tree.", {}),
        ("What kind of database? Do you know Docker? I mean that.", {}),
        ("Like, the cache was, like, sort of slow, literally.", {"like": 2, "sort of": 1, "literally": 1}),
    ],
)
def test_filler_detection(text, expected):
    assert analyse(text, None).filler_words == expected


def test_wpm_and_word_count():
    m = analyse("one two three four five six seven eight nine ten", 5)
    assert m.word_count == 10 and m.wpm == 120.0
    assert analyse("too short to time", 2).wpm is None  # under 3 s is not a reliable rate
    assert analyse("", 30).wpm is None
    assert word_count("It's O(1), isn't it?") == 5


def test_pace_label():
    assert [pace_label(x) for x in (None, 90, 130, 190)] == [None, "slow", "good", "fast"]


# ---------- voice answers through the API ----------

def start(client):
    return client.post("/sessions", json=SETUP).json()["session_id"]


def test_voice_answer_stores_metrics_from_raw_transcript(client, db):
    sid = start(client)
    raw = "um so basically I used a hash map uh because like lookups are fast"
    edited = "I used a hash map because lookups are fast."
    res = client.post(
        f"/sessions/{sid}/answer",
        json={"text": edited, "is_voice": True, "voice_transcript": raw, "speech_seconds": 6},
    )
    assert res.status_code == 200
    answer = db.query(Message).filter_by(speaker="candidate").one()
    assert answer.text == edited  # the edited transcript is the answer (FR-23)
    assert answer.is_voice and answer.speech_seconds == 6
    assert answer.filler_count == 4 and answer.filler_words == {"um": 1, "basically": 1, "uh": 1, "like": 1}
    assert answer.wpm == pytest.approx(14 / 0.1)  # 14 raw words in 6 s


def test_typed_answer_has_no_speech_metrics(client, db):
    sid = start(client)
    client.post(f"/sessions/{sid}/answer", json={"text": "um basically typed"})
    answer = db.query(Message).filter_by(speaker="candidate").one()
    assert not answer.is_voice and answer.filler_count is None and answer.wpm is None


def test_evaluator_is_told_answer_was_spoken(client, fake_llm):
    sid = start(client)
    client.post(f"/sessions/{sid}/answer", json={"text": "spoken", "is_voice": True, "speech_seconds": 4})
    client.post(f"/sessions/{sid}/answer", json={"text": "typed"})
    evals = [c["messages"][0]["content"] for c in fake_llm.calls if c["agent"] == "evaluator"]
    assert "Answer mode: spoken" in evals[0] and "Answer mode: typed" in evals[1]


def test_report_shows_delivery(client):
    sid = start(client)
    client.post(f"/sessions/{sid}/answer", json={
        "text": "a", "is_voice": True, "voice_transcript": "um like one two three four five six seven eight",
        "speech_seconds": 3,
    })
    client.post(f"/sessions/{sid}/answer", json={
        "text": "b", "is_voice": True, "voice_transcript": "uh one two three four five six seven eight nine ten",
        "speech_seconds": 6,
    })
    client.post(f"/sessions/{sid}/answer", json={"text": "typed answer with four words"})
    report = client.post(f"/sessions/{sid}/end").json()

    q1, q2, q3 = report["questions"]
    assert q1["is_voice"] and q1["filler_count"] == 2 and q1["pace"] == "fast"  # 10 words in 3 s = 200 wpm
    assert q2["wpm"] == 110.0 and q2["pace"] == "good"  # 11 words in 6 s
    assert q3["is_voice"] is False and q3["wpm"] is None and q3["word_count"] == 5
    d = report["delivery"]
    assert d["voice_answers"] == 2
    assert d["total_fillers"] == 3 and d["top_fillers"] == {"um": 1, "like": 1, "uh": 1}
    assert d["avg_wpm"] == round((q1["wpm"] + q2["wpm"]) / 2, 1)


def test_text_only_report_has_delivery_without_speech(client):
    sid = start(client)
    client.post(f"/sessions/{sid}/answer", json={"text": "one two"})
    d = client.post(f"/sessions/{sid}/end").json()["delivery"]
    assert d["voice_answers"] == 0 and d["avg_wpm"] is None and d["avg_words_per_answer"] == 2


def test_voice_validation(client):
    sid = start(client)
    bad = client.post(f"/sessions/{sid}/answer", json={"text": "a", "is_voice": True, "speech_seconds": -1})
    assert bad.status_code == 422
    too_long = client.post(f"/sessions/{sid}/answer", json={"text": "a", "voice_transcript": "x" * 5001})
    assert too_long.status_code == 422
