import logging
import queue
import threading
import time
from typing import Callable, Optional

import meshtastic
import meshtastic.serial_interface
from pubsub import pub

from src.utils import chunk_text

logger = logging.getLogger(__name__)

# Type alias: (question, sender_id, is_dm) -> reply string
MessageHandler = Callable[[str, str, bool], str]

# Meshtastic broadcast address
BROADCAST_NUM = 0xFFFFFFFF


class MeshtasticClient:
    def __init__(self, config, on_message: MessageHandler):
        self.mesh_cfg = config.meshtastic
        self.resp_cfg = config.response
        self.on_message = on_message
        self.interface: Optional[meshtastic.serial_interface.SerialInterface] = None
        self.my_node_num: Optional[int] = None
        self._pending_chunks: dict[int, tuple[int, int, str]] = {}
        self._ack_events: dict[int, threading.Event] = {}
        self._msg_queue: queue.Queue = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._shutdown = threading.Event()

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
                self._worker = threading.Thread(
                    target=self._worker_loop, daemon=True, name="mesh-medic-worker"
                )
                self._worker.start()
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
            chunk_info = self._pending_chunks.pop(request_id, None)
            routing = decoded.get("routing", {})
            error = routing.get("errorReason", "NONE")
            if chunk_info is not None:
                chunk_num, total, to_id = chunk_info
                if error == "NONE":
                    logger.info(
                        "ACK chunk %d/%d to %s (packet_id=%s)",
                        chunk_num, total, to_id, request_id,
                    )
                else:
                    logger.warning(
                        "NAK chunk %d/%d to %s: %s (packet_id=%s)",
                        chunk_num, total, to_id, error, request_id,
                    )
            event = self._ack_events.pop(request_id, None)
            if event is not None:
                event.set()
        except Exception as e:
            logger.warning(f"Error in routing handler: {e}")

    def _worker_loop(self):
        logger.info("Worker thread started.")
        while not self._shutdown.is_set():
            try:
                item = self._msg_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            text, from_id, is_dm = item
            try:
                reply = self.on_message(text, from_id, is_dm)
                if reply:
                    self._send_reply(reply, from_id, is_dm)
            except Exception as e:
                logger.error(f"Worker error processing message from {from_id}: {e}", exc_info=True)
        logger.info("Worker thread exiting.")

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
        self._shutdown.set()
        self._msg_queue.put(None)
        if self._worker is not None:
            self._worker.join(timeout=5)
        if self.interface:
            pub.unsubscribe(self._on_receive, "meshtastic.receive.text")
            pub.unsubscribe(self._on_routing, "meshtastic.receive.routing")
            self.interface.close()
            logger.info("Disconnected from Meshtastic device.")

    def _on_receive(self, packet, interface):
        try:
            decoded = packet.get("decoded", {})
            text = decoded.get("text", "").strip()
            if not text:
                return

            from_num = packet.get("from", 0)
            from_id = packet.get("fromId", f"!{from_num:08x}")
            to_num = packet.get("to", BROADCAST_NUM)

            # Ignore our own messages
            if from_num == self.my_node_num:
                return

            is_dm = to_num == self.my_node_num

            if not is_dm and not self.mesh_cfg.respond_to_channels:
                return

            logger.info(
                "[%s] Message from %s (%d chars)",
                "DM" if is_dm else "CH",
                from_id,
                len(text),
            )
            logger.debug("[%s] %s: %r", "DM" if is_dm else "CH", from_id, text)

            self._msg_queue.put((text, from_id, is_dm))

        except Exception as e:
            logger.error(f"Error handling packet: {e}", exc_info=True)

    def _send_reply(self, text: str, to_id: str, is_dm: bool):
        chunks = self._chunk_text(text)
        total = len(chunks)
        self._log_airtime("before_send")

        # For DMs we wait for each chunk's ACK (firmware retry budget ~15-30s)
        # then move on immediately. For channel sends there is no ACK, so fall
        # back to the fixed chunk_delay.
        ack_timeout = float(self.resp_cfg.chunk_delay)
        inter_chunk_gap = 1.0

        for i, chunk in enumerate(chunks):
            payload = f"[{i+1}/{total}] {chunk}" if total > 1 else chunk
            event: Optional[threading.Event] = None
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
                    event = threading.Event()
                    self._pending_chunks[pkt_id] = (i + 1, total, to_id)
                    self._ack_events[pkt_id] = event
                logger.info(
                    f"Sent part {i+1}/{total} to {to_id} (packet_id={pkt_id})"
                )
            except Exception as e:
                logger.error(f"Failed to send message chunk {i+1}: {e}")
                break

            if event is not None:
                t0 = time.monotonic()
                if event.wait(timeout=ack_timeout):
                    logger.info(
                        "Chunk %d/%d resolved in %.1fs",
                        i + 1, total, time.monotonic() - t0,
                    )
                else:
                    # Drop orphaned state — ACK never arrived
                    self._pending_chunks.pop(pkt_id, None)
                    self._ack_events.pop(pkt_id, None)
                    logger.warning(
                        "No ACK for chunk %d/%d within %.0fs — continuing",
                        i + 1, total, ack_timeout,
                    )
                if i < total - 1:
                    time.sleep(inter_chunk_gap)
            else:
                # Channel send: no ACK semantics, use fixed delay
                if i < total - 1:
                    time.sleep(self.resp_cfg.chunk_delay)

        self._log_airtime("after_send")

    def _chunk_text(self, text: str) -> list[str]:
        return chunk_text(
            text,
            self.resp_cfg.max_chunk_size,
            max_chunks=self.resp_cfg.max_chunks,
        )
