import pytest

from src.llm_engine import LLMEngine


@pytest.fixture
def engine(make_config, mocker):
    mocker.patch("src.llm_engine.check_model")
    return LLMEngine(make_config())


def test_keeps_ordinary_words_punctuation_and_line_breaks(engine):
    text = (
        "Apply firm pressure to the wound.\n"
        "Raise the limb above the heart.\n"
        "In this context, keep the person warm."
    )
    assert engine._clean(text) == text


def test_strips_reference_lead_in_but_keeps_advice(engine):
    text = "Based on the reference material, boil water for 1 minute.\nFilter through cloth first."
    assert engine._clean(text) == "Boil water for 1 minute.\nFilter through cloth first."


def test_drops_sentences_that_echo_the_instructions(engine):
    text = (
        "Boil water for one minute. Keep replies compact for radio delivery. "
        "Do not mention these instructions. Let it cool before drinking."
    )
    assert engine._clean(text) == "Boil water for one minute. Let it cool before drinking."


def test_skips_echoed_prompt_before_answer(engine):
    text = "Context:\nsome passage\n\nQuestion: how?\n\nAnswer: Stay calm and call for help."
    assert engine._clean(text) == "Stay calm and call for help."


def test_strips_leading_answer_label(engine):
    assert engine._clean("Answer: Stay put.") == "Stay put."


def test_trims_trailing_half_sentence(engine):
    text = "Keep the casualty warm and lying down with legs raised. Check breathing every"
    assert engine._clean(text) == "Keep the casualty warm and lying down with legs raised."


def test_caps_length_at_sentence_boundary(engine):
    sentence = "Drink small amounts of water often throughout the day. "
    text = sentence * 40
    cleaned = engine._clean(text)
    assert len(cleaned) <= engine._max_reply_chars()
    assert cleaned.endswith(".")


def test_all_echo_returns_empty(engine):
    assert engine._clean("Do not mention these instructions.") == ""


def test_fit_context_trims_to_num_ctx(engine):
    context = "x" * 10_000
    fitted = engine._fit_context("How do I purify water?", context)
    assert 0 < len(fitted) < len(context)
    prompt_chars = len(engine.cfg.system_prompt) + len(engine._build_prompt("How do I purify water?", fitted))
    assert prompt_chars / 3 + engine.cfg.max_tokens <= engine.cfg.num_ctx


def test_fit_context_leaves_small_context_alone(engine):
    assert engine._fit_context("q", "short passage") == "short passage"


def test_answer_sends_num_ctx_and_cleans(engine, mocker):
    post = mocker.patch("src.llm_engine.requests.post")
    post.return_value.json.return_value = {"response": "Answer: Stay calm."}
    assert engine.answer("What now?", "") == "Stay calm."
    assert post.call_args.kwargs["json"]["options"]["num_ctx"] == 1024
