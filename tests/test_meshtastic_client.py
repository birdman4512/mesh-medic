import threading
from types import SimpleNamespace

import pytest

from src.meshtastic_client import MeshtasticClient

MY_NODE = 0x1234


@pytest.fixture
def client(make_config):
    received = []
    c = MeshtasticClient(make_config(), on_message=lambda *args: received.append(args))
    c.my_node_num = MY_NODE
    c.interface = SimpleNamespace(nodes={}, sendText=None)
    c.received = received
    return c


def routing(request_id, error="NONE"):
    return {"decoded": {"requestId": request_id, "routing": {"errorReason": error}}}


def test_dm_is_handed_to_dispatcher_with_reply_fn(client):
    client._on_receive(
        {"decoded": {"text": " hi "}, "from": 0x99, "fromId": "!00000099", "to": MY_NODE}, None
    )
    text, sender, is_dm, reply = client.received[0]
    assert (text, sender, is_dm) == ("hi", "!00000099", True)
    assert reply.keywords == {"to_id": "!00000099", "is_dm": True}


def test_channel_messages_ignored_unless_enabled_and_on_configured_channel(client):
    pkt = {"decoded": {"text": "hi"}, "from": 0x99, "to": 0xFFFFFFFF, "channel": 1}
    client._on_receive(pkt, None)
    client.mesh_cfg.respond_to_channels = True
    client._on_receive(pkt, None)
    assert client.received == []
    client._on_receive({**pkt, "channel": 0}, None)
    assert len(client.received) == 1


def test_ignores_own_messages(client):
    client._on_receive({"decoded": {"text": "hi"}, "from": MY_NODE, "to": MY_NODE}, None)
    assert client.received == []


def test_ack_arriving_before_registration_is_not_lost(client):
    client._on_routing(routing(42), None)
    waiter = client._register_ack(42)
    assert waiter.event.is_set()
    assert waiter.error == "NONE"


def test_send_reply_waits_for_each_ack(client):
    sent = []

    def send_text(payload, destinationId=None, wantAck=False, **kw):
        pkt_id = len(sent) + 1
        sent.append(payload)
        # ACK arrives from the radio thread shortly after the send
        threading.Timer(0.01, client._on_routing, (routing(pkt_id), None)).start()
        return SimpleNamespace(id=pkt_id)

    client.interface.sendText = send_text
    client._send_reply("First sentence here. " * 20, to_id="!00000099", is_dm=True)
    assert len(sent) > 1
    assert sent[0].startswith(f"[1/{len(sent)}] ")
    assert client._ack_waiters == {}


def test_send_reply_continues_after_ack_timeout(client):
    sent = []

    def send_text(payload, **kw):
        sent.append(payload)
        return SimpleNamespace(id=len(sent))

    client.interface.sendText = send_text
    client.resp_cfg.ack_timeout = 0.01
    client._send_reply("Part one is here. " * 20, to_id="!00000099", is_dm=True)
    assert len(sent) > 1
    assert client._ack_waiters == {}


def test_connection_lost_sets_event(client):
    client._on_connection_lost(interface=None)
    assert client.connection_lost.is_set()
