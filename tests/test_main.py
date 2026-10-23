from types import SimpleNamespace

from src.main import NO_ANSWER_REPLY, build_handler
from src.rag_engine import Retrieval


def make(answer, citations=("guide.pdf p.3",)):
    rag = SimpleNamespace(retrieve=lambda q: Retrieval("ctx", list(citations)))
    llm = SimpleNamespace(answer=lambda q, c: answer)
    return rag, llm


def test_handler_appends_citation_when_enabled():
    handler = build_handler(*make("Boil it."), cite_sources=True)
    assert handler("water?", "a", True) == "Boil it.\n[guide.pdf p.3]"


def test_handler_without_citation_by_default():
    assert build_handler(*make("Boil it."))("water?", "a", True) == "Boil it."


def test_handler_falls_back_when_answer_empty():
    handler = build_handler(*make(""), cite_sources=True)
    assert handler("water?", "a", True) == NO_ANSWER_REPLY
