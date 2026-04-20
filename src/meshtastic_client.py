import logging
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

    def connect(self):
        logger.info(f"Connecting to Meshtastic device at {self.mesh_cfg.device}")
        self.interface = meshtastic.serial_interface.SerialInterface(self.mesh_cfg.device)
        self.my_node_num = self.interface.myInfo.my_node_num
        logger.info(f"Connected. Node: !{self.my_node_num:08x}")
        pub.subscribe(self._on_receive, "meshtastic.receive.text")
        logger.info("Listening for messages...")

    def disconnect(self):
        if self.interface:
            pub.unsubscribe(self._on_receive, "meshtastic.receive.text")
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

            logger.info(f"[{'DM' if is_dm else 'CH'}] {from_id}: {text}")

            reply = self.on_message(text, from_id, is_dm)
            if reply:
                self._send_reply(reply, from_id, is_dm)

        except Exception as e:
            logger.error(f"Error handling packet: {e}", exc_info=True)

    def _send_reply(self, text: str, to_id: str, is_dm: bool):
        chunks = self._chunk_text(text)
        total = len(chunks)

        for i, chunk in enumerate(chunks):
            payload = f"[{i+1}/{total}] {chunk}" if total > 1 else chunk

            try:
                if is_dm:
                    self.interface.sendText(payload, destinationId=to_id)
                else:
                    self.interface.sendText(
                        payload, channelIndex=self.mesh_cfg.channel_index
                    )
                logger.info(f"Sent part {i+1}/{total} to {to_id}")
            except Exception as e:
                logger.error(f"Failed to send message chunk {i+1}: {e}")
                break

            if i < total - 1:
                time.sleep(self.resp_cfg.chunk_delay)

    def _chunk_text(self, text: str) -> list[str]:
        return chunk_text(text, self.resp_cfg.max_chunk_size)
