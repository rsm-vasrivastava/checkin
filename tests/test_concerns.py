"""Regression tests for a bug found in live voice-mode testing: the senior said
"I was having problem in listening to them", yet concerns was [], urgency "ok"-ish, and the closing
said "you're doing well". Run: .venv/bin/python -m pytest"""
import pytest

from checkin import llm, pipeline

PHRASES = [
    "I was having problem in listening to them",   # the live-test sentence
    "I have a problem hearing you",
    "I can't hear very well",
    "I have trouble listening on the phone",
    "I feel dizzy this morning",
    "I am a bit confused today",
]


def _transcript(said):
    return [{"role": "ai", "text": "Hello Margaret, how are you?"}, {"role": "senior", "text": said}]


@pytest.mark.parametrize("said", PHRASES)
def test_summary_records_concern_and_is_at_least_watch(model, said):
    model()  # the "model" claims: no concerns, urgency ok, doing well, which is exactly the bug
    s = llm.summarize("Margaret", "en", _transcript(said))
    assert s["concerns"], f"concern missed for: {said}"
    assert s["urgency"] in ("watch", "urgent")


def test_live_sentence_gets_a_clear_label_and_shows_in_summary_text(model):
    model()
    s = llm.summarize("Margaret", "en", _transcript("I was having problem in listening to them"))
    assert "Difficulty hearing" in s["concerns"]
    assert "hearing" in s["summary_text"].lower()  # family sees it even if the model's text did not mention it


@pytest.mark.parametrize("said", ["I feel dizzy", "I am confused"])
def test_dizzy_and_confused_are_not_pain(model, said):
    model()
    assert llm.summarize("Margaret", "en", _transcript(said))["pain_or_fall"] is None


@pytest.mark.parametrize("said", ["No problem at all, thank you", "I can't complain", "I don't hear from my son much"])
def test_no_false_alarm(model, said):
    model()
    s = llm.summarize("Margaret", "en", _transcript(said))
    assert s["concerns"] == [] and s["urgency"] == "ok"


@pytest.mark.parametrize("said", PHRASES)
def test_closing_never_says_doing_well_after_a_concern(model, said):
    model(reply="You're doing well, Margaret! Take care.")  # a model that ignores the instructions
    transcript = [{"role": "ai", "text": "Hi"}, {"role": "senior", "text": said}]
    out = llm.next_turn("Margaret", "en", [], [], transcript + [{"role": "ai", "text": "?"}, {"role": "senior", "text": "goodbye"}], 3)
    assert out["end"] and "doing well" not in out["say"].lower()
    assert "thank you" in out["say"].lower() and "family" in out["say"].lower() and "update" in out["say"].lower()


def test_closing_without_concerns_asks_model_to_thank_and_promise_an_update(model):
    seen = model(reply="Thank you for chatting, Margaret. Your family will get an update.")
    t = [{"role": "ai", "text": "Hi"}, {"role": "senior", "text": "all good"}, {"role": "ai", "text": "?"}, {"role": "senior", "text": "bye"}]
    out = llm.next_turn("Margaret", "en", [], [], t, 3)
    assert out["end"] and "family will get an update" in seen[-1]


def test_every_call_asks_about_pain_or_falls_as_its_own_question(model):
    """Drive a whole call. Even if the model rambles and asks its own off-topic questions, the
    pain/falls question is spoken by code, exactly once, as the last sentence of its own turn."""
    model(reply="Tell me more about that?")
    asked = []
    replies = iter(["I'm well", "yes", "yes", "no", "no", "no", "no"])
    pipeline.run_conversation("Margaret", "en", "t", asked.append, lambda: next(replies, "no"))
    turns = [a for a in asked if llm.PAIN_QUESTION in a]
    assert len(turns) == 1 and turns[0].endswith(llm.PAIN_QUESTION)
    assert turns[0].count("?") == 1, f"pain question must be alone in its turn: {turns[0]}"
    order = [i for i, a in enumerate(asked) if "medication" in a or "eaten" in a or llm.PAIN_QUESTION in a]
    assert [("medication" in asked[i], "eaten" in asked[i]) for i in order[:2]] == [(True, False), (False, True)]


def test_pain_question_follows_up_on_yesterday_but_is_still_asked(model):
    model()
    history = [{"pain_or_fall": "my knee hurts", "concerns": [], "trend_flags": [], "summary_text": "knee"}]
    t = [{"role": "ai", "text": "Hi"}, {"role": "senior", "text": "ok"}, {"role": "ai", "text": "meds?"},
         {"role": "senior", "text": "yes"}, {"role": "ai", "text": "eaten?"}, {"role": "senior", "text": "yes"}]
    say = llm.next_turn("Margaret", "en", history, ["Did you call your sister?"], t, 4)["say"]
    assert "my knee hurts" in say and say.endswith(llm.PAIN_QUESTION)


def test_family_questions_are_asked_before_the_call_ends(model):
    model()
    t = [{"role": "ai", "text": "Hi"}]
    for r in ["ok", "yes", "yes", "no pain"]:
        t += [{"role": "senior", "text": r}, {"role": "ai", "text": "q"}]
    t = t[:-1]
    say = llm.next_turn("Margaret", "en", [], ["Did you call your sister?"], t, 5)["say"]
    assert "Did you call your sister?" in say


def test_concern_dedupe_and_no_false_pill_concern(model):
    model('{"meds_taken": true, "ate": true, "mood": "ok", "pain_or_fall": null, '
          '"concerns": ["Trouble hearing", "Forgot to take pills"], "urgency": "ok", "summary_text": "ok"}')
    s = llm.summarize("Margaret", "en", [{"role": "senior", "text": "I had problem in listening. Yes I took my pills."}])
    assert [c.lower() for c in s["concerns"]] == ["difficulty hearing"]  # model wording was ungrounded; code label used


def test_emergency_and_no_response_still_work(model):
    model()
    assert llm.summarize("M", "en", _transcript("I fell in the kitchen"))["urgency"] == "urgent"
    assert llm.summarize("M", "en", [{"role": "ai", "text": "Hi"}])["concerns"] == ["No response to the call"]


def test_negations_from_the_model_are_not_concerns(model):
    """Found with the real local model: a healthy call came back with concerns ['No pain', 'No falls'],
    which (since concerns force 'watch') wrongly flagged it."""
    model('{"meds_taken": true, "ate": true, "mood": "good", "pain_or_fall": "No falls", '
          '"concerns": ["No pain", "No falls", "Nothing else"], "urgency": "ok", "summary_text": "Doing great."}')
    s = llm.summarize("Margaret", "en", [{"role": "senior", "text": "I'm doing great. No pain, no falls."}])
    assert s["concerns"] == [] and s["pain_or_fall"] is None and s["urgency"] == "ok"


def test_invented_concerns_are_dropped_and_duplicates_collapsed(model):
    """Real-model finding: a healthy call came back with the invented concern 'Eating breakfast' (-> watch),
    and a hearing call with two worded-differently copies of the same concern."""
    model('{"meds_taken": true, "ate": true, "mood": "good", "pain_or_fall": null, '
          '"concerns": ["Eating breakfast"], "urgency": "ok", "summary_text": "Doing great."}')
    healthy = llm.summarize("Margaret", "en", [{"role": "senior", "text": "I am doing great, I had toast."}])
    assert healthy["concerns"] == [] and healthy["urgency"] == "ok"
    model('{"meds_taken": true, "ate": true, "mood": "ok", "pain_or_fall": null, '
          '"concerns": ["problem hearing", "had problem listening"], "urgency": "watch", "summary_text": "Hearing issues."}')
    s = llm.summarize("Margaret", "en", [{"role": "senior", "text": "I had problem listening to them"}])
    assert len(s["concerns"]) == 1
