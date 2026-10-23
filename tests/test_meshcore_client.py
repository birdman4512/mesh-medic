import asyncio
from types import SimpleNamespace

import pytest

from src.meshcore_client import MeshCoreClient, _contact_key, _keys_match, _split_sender


@pytest.fixture
def client(make_config):
    received = []
    c = MeshCoreClient(make_config("meshcore"), on_message=lambda *args: received.append(args))
    c.received = received
    return c


def test_contact_key_handles_dicts_and_objects():
    assert _contact_key({"public_key": "abcdef0123"}) == "abcdef0123"
    assert _contact_key(SimpleNamespace(pubkey_prefix="abcdef")) == "abcdef"


def test_keys_match_on_prefix():
    assert _keys_match("abcdef", "abcdef0123")
    assert _keys_match("abcdef0123", "abcdef")
    assert not _keys_match("", "abcdef")
    assert not _keys_match("abcdee", "abcdef0123")


def test_split_sender():
    assert _split_sender("Bob: ? how to purify water") == ("Bob", "? how to purify water")
    assert _split_sender("no sender here") == ("", "no sender here")


def test_room_question_uses_per_user_sender_id(client):
    client._room_pubkey = "abcdef0123"
    client._handle_room_message("Bob: ? how do I start a fire")
    client._handle_room_message("Ann: just chatting")
    assert len(client.received) == 1
    question, sender, is_dm, _ = client.received[0]
    assert (question, sender, is_dm) == ("how do I start a fire", "room:Bob", False)


def test_channel_send_uses_send_chan_msg_with_delay(client):
    calls = []

    async def send_chan_msg(idx, msg):
        calls.append((idx, msg))
        return SimpleNamespace(type=None)

    client._mc = SimpleNamespace(commands=SimpleNamespace(send_chan_msg=send_chan_msg))
    asyncio.run(client._send_to_channel("Sentence number one is here. " * 12))
    assert len(calls) > 1
    assert all(idx == 0 for idx, _ in calls)
    assert all(len(m.encode()) <= 160 for _, m in calls)


def test_dm_send_uses_retry_with_ack(client):
    calls = []

    async def get_contacts():
        return SimpleNamespace(type=None, payload={"abcdef0123": {"public_key": "abcdef0123"}})

    async def send_msg_with_retry(contact, msg):
        calls.append(msg)
        return SimpleNamespace(type=None)

    client._mc = SimpleNamespace(
        commands=SimpleNamespace(get_contacts=get_contacts, send_msg_with_retry=send_msg_with_retry)
    )
    asyncio.run(client._send_to_contact("Short answer.", "abcdef"))
    assert calls == ["Short answer."]


def test_disconnect_event_sets_connection_lost(client):
    asyncio.run(client._on_disconnected(SimpleNamespace(payload={"reason": "serial_disconnect"})))
    assert client.connection_lost.is_set()


def test_manual_disconnect_is_ignored(client):
    asyncio.run(client._on_disconnected(SimpleNamespace(payload={"reason": "manual_disconnect"})))
    assert not client.connection_lost.is_set()
