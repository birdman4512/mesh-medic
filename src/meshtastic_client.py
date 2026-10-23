import functools
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Optional

import meshtastic
import meshtastic.serial_interface
from pubsub import pub

from src.utils import chunk_text

logger = logging.getLogger(__name__)

# (question, sender_id, is_dm, reply_fn) -> None. The handler queues the question and
# later calls reply_fn(answer) from a worker thread.
MessageHandler = Callable[[str, str, bool, Callable[[str], None]], None]

# Meshtastic broadcast address
BROADCAST_NUM = 0xFFFFFFFF

# Pause after an ACKed part before sending the next one
INTER_CHUNK_GAP = 1.0
# ACKs that arrive before we registered their packet id are kept briefly
MAX_EARLY_ACKS = 64


@dataclass
class _AckWaiter:
    event: threading.Event = field(default_factory=threading.Event)
    error: Optional[str] = None


class MeshtasticClient:
    def __init__(self, config, on_message: MessageHandler):
        self.mesh_cfg = config.meshtastic
        self.resp_cfg = config.response
        self.on_message = on_message
        self.interface: Optional[meshtastic.serial_interface.SerialInterface] = None
        self.my_node_num: Optional[int] = None
        self.connection_lost = threading.Event()
        self._ack_lock = threading.Lock()
        self._ack_waiters: dict[int, _AckWaiter] = {}
        self._early_acks: "OrderedDict[int, str]" = OrderedDict()

    def connect(self, retries: int = 10, retry_delay: float = 15.0):
        for attempt in range(1, retries + 1):
            try:
                logger.info(
                    f"Connecting to Meshtastic device at {self.mesh_cfg.device}"
                    f" (attempt {attempt}/{retries})"
                )
                self.interface = meshtastic.serial_interface.SerialInterface(
                    self.mesh_cfg.device
                )
                self.my_node_num = self.interface.myInfo.my_node_num
                logger.info(f"Connected. Node: !{self.my_node_num:08x}")
                self._log_radio_config()
                pub.subscribe(self._on_receive, "meshtastic.receive.text")
                pub.subscribe(self._on_routing, "meshtastic.receive.routing")
                pub.subscribe(self._on_connection_lost, "meshtastic.connection.lost")
                logger.info("Listening for messages...")
                return
            except Exception as e:
                logger.warning(f"Connection attempt {attempt} failed: {e}")
                if attempt < retries:
                    logger.info(f"Retrying in {retry_delay:.0f}s...")
                    time.sleep(retry_delay)
        raise RuntimeError(
            f"Could not connect to {self.mesh_cfg.device} after {retries} attempts. "
            "Unplug and replug the USB cable, then restart the service."
        )

    def _on_connection_lost(self, interface=None):
        logger.error("Lost connection to Meshtastic device %s", self.mesh_cfg.device)
        self.connection_lost.set()

    def _log_airtime(self, when: str):
        try:
            my_id = f"!{self.my_node_num:08x}"
            node = self.interface.nodes.get(my_id, {}) if self.interface.nodes else {}
            metrics = node.get("deviceMetrics", {}) if isinstance(node, dict) else {}
            air_tx = metrics.get("airUtilTx")
            ch_util = metrics.get("channelUtilization")
            logger.info(
                "Airtime (%s): air_util_tx=%s%% channel_utilization=%s%%",
                when,
                f"{air_tx:.2f}" if isinstance(air_tx, (int, float)) else "?",
                f"{ch_util:.2f}" if isinstance(ch_util, (int, float)) else "?",
            )
        except Exception as e:
            logger.debug(f"Could not read airtime metrics: {e}")

    def _on_routing(self, packet, interface):
        try:
            decoded = packet.get("decoded", {})
            request_id = decoded.get("requestId")
            if request_id is None:
                return
            error = decoded.get("routing", {}).get("errorReason", "NONE")
            with self._ack_lock:
                waiter = self._ack_waiters.pop(request_id, None)
                if waiter is None:
                    # The ACK can beat sendText() returning the packet id to us.
                    self._early_acks[request_id] = error
                    while len(self._early_acks) > MAX_EARLY_ACKS:
                        self._early_acks.popitem(last=False)
                    return
            waiter.error = error
            waiter.event.set()
        except Exception as e:
            logger.warning(f"Error in routing handler: {e}")

    def _log_radio_config(self):
        try:
            lora = self.interface.localNode.localConfig.lora
            from meshtastic.protobuf import config_pb2
            preset = config_pb2.Config.LoRaConfig.ModemPreset.Name(lora.modem_preset)
            region = config_pb2.Config.LoRaConfig.RegionCode.Name(lora.region)
            if lora.use_preset:
                radio = f"preset={preset}"
            else:
                radio = (
                    f"preset=CUSTOM (bw={lora.bandwidth} sf={lora.spread_factor} "
                    f"cr={lora.coding_rate})"
                )
            ch_name = ""
            try:
                ch_name = self.interface.localNode.channels[0].settings.name or "(default)"
            except Exception:
                ch_name = "?"
            logger.info(
                "Radio config: region=%s %s primary_channel=%r",
                region, radio, ch_name,
            )
        except Exception as e:
            logger.warning(f"Could not read radio config: {e}")

    def disconnect(self):
        if self.interface:
            for listener, topic in (
                (self._on_receive, "meshtastic.receive.text"),
                (self._on_routing, "meshtastic.receive.routing"),
                (self._on_connection_lost, "meshtastic.connection.lost"),
            ):
                try:
                    pub.unsubscribe(listener, topic)
                except Exception:
                    pass
            try:
                self.interface.close()
            except Exception as e:
                logger.warning(f"Error closing Meshtastic interface: {e}")
            logger.info("Disconnected from Meshtastic device.")

    def _on_receive(self, packet, interface):
        try:
            decoded = packet.get("decoded", {})
            text = decoded.get("text", "").strip()
            if not text:
                return

            from_num = packet.get("from", 0)
            from_id = packet.get("fromId") or f"!{from_num:08x}"
            to_num = packet.get("to", BROADCAST_NUM)

            # Ignore our own messages
            if from_num == self.my_node_num:
                return

            is_dm = to_num == self.my_node_num

            if not is_dm:
                if not self.mesh_cfg.respond_to_channels:
                    return
                if packet.get("channel", 0) != self.mesh_cfg.channel_index:
                    return

            logger.info(
                "[%s] Message from %s (%d chars)",
                "DM" if is_dm else "CH",
                from_id,
                len(text),
            )
            logger.debug("[%s] %s: %r", "DM" if is_dm else "CH", from_id, text)

            reply = functools.partial(self._send_reply, to_id=from_id, is_dm=is_dm)
            self.on_message(text, from_id, is_dm, reply)

        except Exception as e:
            logger.error(f"Error handling packet: {e}", exc_info=True)

    def _register_ack(self, pkt_id: int) -> _AckWaiter:
        waiter = _AckWaiter()
        with self._ack_lock:
            if pkt_id in self._early_acks:
                waiter.error = self._early_acks.pop(pkt_id)
                waiter.event.set()
            else:
                self._ack_waiters[pkt_id] = waiter
        return waiter

    def _send_reply(self, text: str, to_id: str, is_dm: bool):
        chunks = self._chunk_text(text)
        total = len(chunks)
        self._log_airtime("before_send")

        for i, chunk in enumerate(chunks):
            payload = f"[{i+1}/{total}] {chunk}" if total > 1 else chunk
            waiter: Optional[_AckWaiter] = None
            pkt_id: Optional[int] = None

            try:
                if is_dm:
                    pkt = self.interface.sendText(
                        payload, destinationId=to_id, wantAck=True
                    )
                else:
                    pkt = self.interface.sendText(
                        payload, channelIndex=self.mesh_cfg.channel_index
                    )
                pkt_id = getattr(pkt, "id", None) if pkt is not None else None
                if pkt_id is not None and is_dm:
                    waiter = self._register_ack(pkt_id)
                logger.info(
                    f"Sent part {i+1}/{total} to {to_id} (packet_id={pkt_id})"
                )
            except Exception as e:
                logger.error(f"Failed to send message chunk {i+1}: {e}")
                break

            if waiter is not None:
                # DMs: wait for this part's ACK (firmware retries for ~15-30s), then move on.
                t0 = time.monotonic()
                if waiter.event.wait(timeout=self.resp_cfg.ack_timeout):
                    elapsed = time.monotonic() - t0
                    if waiter.error == "NONE":
                        logger.info(
                            "ACK chunk %d/%d to %s in %.1fs (packet_id=%s)",
                            i + 1, total, to_id, elapsed, pkt_id,
                        )
                    else:
                        logger.warning(
                            "NAK chunk %d/%d to %s: %s (packet_id=%s)",
                            i + 1, total, to_id, waiter.error, pkt_id,
                        )
                else:
                    with self._ack_lock:
                        self._ack_waiters.pop(pkt_id, None)
                    logger.warning(
                        "No ACK for chunk %d/%d within %.0fs — continuing",
                        i + 1, total, self.resp_cfg.ack_timeout,
                    )
                if i < total - 1:
                    time.sleep(INTER_CHUNK_GAP)
            elif i < total - 1:
                # Channel send: no ACK semantics, use fixed delay
                time.sleep(self.resp_cfg.chunk_delay)

        self._log_airtime("after_send")

    def _chunk_text(self, text: str) -> list[str]:
        return chunk_text(
            text,
            self.resp_cfg.max_chunk_size,
            max_chunks=self.resp_cfg.max_chunks,
        )
