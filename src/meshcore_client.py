import asyncio
import logging
import threading
from typing import Callable, Optional

from meshcore import EventType, MeshCore

from src.utils import chunk_text

logger = logging.getLogger(__name__)

MessageHandler = Callable[[str, str, bool], str]

# MeshCore max payload is 184 bytes; 160 chars leaves headroom for chunk labels
MESHCORE_MAX_CHUNK = 160


class MeshCoreClient:
    def __init__(self, config, on_message: MessageHandler):
        self.mc_cfg = config.meshcore
        self.resp_cfg = config.response
        self.on_message = on_message
        self._mc: Optional[MeshCore] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._room_pubkey: Optional[str] = None  # set after successful room login

    def connect(self, retries: int = 10, retry_delay: float = 15.0):
        self._loop = asyncio.new_event_loop()
        loop_ready = threading.Event()

        def run_loop():
            asyncio.set_event_loop(self._loop)
            self._loop.call_soon(loop_ready.set)
            self._loop.run_forever()

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()
        loop_ready.wait()

        future = asyncio.run_coroutine_threadsafe(
            self._async_connect(retries, retry_delay), self._loop
        )
        future.result()

    async def _async_connect(self, retries: int, retry_delay: float):
        for attempt in range(1, retries + 1):
            try:
                logger.info(
                    f"Connecting to MeshCore device at {self.mc_cfg.device}"
                    f" (attempt {attempt}/{retries})"
                )
                self._mc = await MeshCore.create_serial(self.mc_cfg.device, 115200)
                self._mc.subscribe(EventType.CONTACT_MSG_RECV, self._on_contact_message)
                if self.mc_cfg.respond_to_channels:
                    self._mc.subscribe(EventType.CHANNEL_MSG_RECV, self._on_channel_message)
                await self._mc.start_auto_message_fetching()
                if self.mc_cfg.room_server:
                    await self._join_room()
                logger.info("Connected to MeshCore device. Listening for messages...")
                return
            except Exception as e:
                logger.warning(f"Connection attempt {attempt} failed: {e}")
                if attempt < retries:
                    logger.info(f"Retrying in {retry_delay:.0f}s...")
                    await asyncio.sleep(retry_delay)
        raise RuntimeError(
            f"Could not connect to {self.mc_cfg.device} after {retries} attempts. "
            "Unplug and replug the USB cable, then restart the service."
        )

    def disconnect(self):
        if self._loop and self._loop.is_running():
            if self._mc is not None:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_disconnect(), self._loop
                )
                try:
                    future.result(timeout=10)
                except Exception as e:
                    logger.warning(f"MeshCore disconnect cleanup failed: {e}")
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Disconnected from MeshCore device.")

    async def _async_disconnect(self):
        if self._mc is None:
            return

        await self._mc.disconnect()
        self._mc = None

        # Let serial_asyncio finish transport shutdown callbacks before we
        # stop the event loop underneath it.
        await asyncio.sleep(0.25)

        current = asyncio.current_task()
        pending = [
            task
            for task in asyncio.all_tasks()
            if task is not current and not task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _join_room(self):
        contact = await self._find_contact(self.mc_cfg.room_server)
        if not contact:
            logger.warning(f"Room server {self.mc_cfg.room_server!r} not found in contacts")
            return
        self._room_pubkey = getattr(contact, "pubkey_prefix", "")
        result = await self._mc.commands.send_login(contact, pwd=self.mc_cfg.room_password)
        if getattr(result, "type", None) == EventType.ERROR:
            logger.warning(f"Room server login failed: {result.payload}")
        else:
            logger.info(
                f"Joined room server {self.mc_cfg.room_server!r} "
                f"(trigger: {self.mc_cfg.room_trigger!r})"
            )

    def _is_room_sender(self, sender: str) -> bool:
        if not self._room_pubkey:
            return False
        return (
            sender == self._room_pubkey
            or sender.startswith(self._room_pubkey)
            or self._room_pubkey.startswith(sender)
        )

    async def _on_contact_message(self, event):
        try:
            payload = event.payload or {}
            text = payload.get("text", "").strip()
            sender = payload.get("pubkey_prefix", "unknown")
            if not text:
                return
            if self._is_room_sender(sender):
                await self._handle_room_message(text)
                return
            logger.info("[DM] Message from %s (%d chars)", sender, len(text))
            logger.debug("[DM] %s: %r", sender, text)
            loop = asyncio.get_running_loop()
            reply = await loop.run_in_executor(None, self.on_message, text, sender, True)
            if reply:
                await self._send_to_contact(reply, sender)
        except Exception as e:
            logger.error(f"Error handling contact message: {e}", exc_info=True)

    async def _handle_room_message(self, text: str):
        # Room server relays messages as "SenderName: body"
        _, sep, body = text.partition(": ")
        message = body.strip() if sep else text.strip()

        trigger = self.mc_cfg.room_trigger
        if not message.startswith(trigger):
            return

        question = message[len(trigger):].strip()
        if not question:
            return

        logger.info("[ROOM] Question received (%d chars)", len(question))
        logger.debug("[ROOM] question: %r", question)
        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(None, self.on_message, question, "room", False)
        if reply and self._room_pubkey:
            await self._send_to_contact(reply, self._room_pubkey)

    async def _on_channel_message(self, event):
        try:
            payload = event.payload or {}
            text = payload.get("text", "").strip()
            sender = payload.get("pubkey_prefix", "unknown")
            if not text:
                return
            logger.info("[CH] Message from %s (%d chars)", sender, len(text))
            logger.debug("[CH] %s: %r", sender, text)
            loop = asyncio.get_running_loop()
            reply = await loop.run_in_executor(None, self.on_message, text, sender, False)
            if reply:
                await self._send_to_channel(reply)
        except Exception as e:
            logger.error(f"Error handling channel message: {e}", exc_info=True)

    async def _find_contact(self, pubkey_prefix: str):
        result = await self._mc.commands.get_contacts()
        if not result.payload:
            return None
        contacts = result.payload
        if isinstance(contacts, dict):
            for public_key, contact in contacts.items():
                cp = (
                    contact.get("public_key")
                    or contact.get("pubkey_prefix")
                    or public_key
                    or ""
                )
                if cp == pubkey_prefix or cp.startswith(pubkey_prefix):
                    return contact
            return None

        for contact in contacts:
            cp = getattr(contact, "pubkey_prefix", "") or getattr(contact, "public_key", "")
            if cp == pubkey_prefix or cp.startswith(pubkey_prefix):
                return contact
        return None

    async def _send_to_contact(self, text: str, pubkey_prefix: str):
        contact = await self._find_contact(pubkey_prefix)
        if not contact:
            logger.warning(f"No contact found for pubkey prefix {pubkey_prefix!r}")
            return
        await self._send_chunks(
            text, lambda part: self._mc.commands.send_msg(contact, part)
        )

    async def _send_to_channel(self, text: str):
        result = await self._mc.commands.get_channels()
        channel = None
        if result.payload:
            for ch in result.payload:
                if getattr(ch, "idx", 0) == self.mc_cfg.channel_index:
                    channel = ch
                    break
            if not channel:
                channel = result.payload[0]
        if not channel:
            logger.warning("No channel available for reply")
            return
        await self._send_chunks(
            text, lambda part: self._mc.commands.send_channel_msg(channel, part)
        )

    async def _send_chunks(self, text: str, send_fn):
        max_size = min(self.resp_cfg.max_chunk_size, MESHCORE_MAX_CHUNK)
        parts = chunk_text(text, max_size, max_chunks=self.resp_cfg.max_chunks)
        total = len(parts)
        for i, part in enumerate(parts):
            payload = f"[{i+1}/{total}] {part}" if total > 1 else part
            try:
                await send_fn(payload)
                logger.info(f"Sent part {i+1}/{total}")
            except Exception as e:
                logger.error(f"Failed to send chunk {i+1}: {e}")
                break
            if i < total - 1:
                await asyncio.sleep(self.resp_cfg.chunk_delay)
