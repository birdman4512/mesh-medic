import asyncio
import logging
import threading
from typing import Callable, Optional

from meshcore import EventType, MeshCore

from src.utils import chunk_text

logger = logging.getLogger(__name__)

# (question, sender_id, is_dm, reply_fn) -> None; see meshtastic_client.MessageHandler
MessageHandler = Callable[[str, str, bool, Callable[[str], None]], None]

# MeshCore max text payload is ~184 bytes; 160 leaves headroom for chunk labels
MESHCORE_MAX_CHUNK = 160

# Pause after an ACKed part before sending the next one
INTER_CHUNK_GAP = 1.0


def _contact_key(contact) -> str:
    """Public key (or prefix) of a contact, whether the library gave us a dict or an object."""
    if isinstance(contact, dict):
        return contact.get("public_key") or contact.get("pubkey_prefix") or ""
    return getattr(contact, "public_key", "") or getattr(contact, "pubkey_prefix", "") or ""


def _keys_match(a: str, b: str) -> bool:
    """MeshCore identifies nodes by full keys or 6-byte prefixes; treat a prefix as a match."""
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def _split_sender(text: str) -> tuple[str, str]:
    """Room and channel messages arrive as "SenderName: body"."""
    name, sep, body = text.partition(": ")
    if sep and name and len(name) <= 32:
        return name.strip(), body.strip()
    return "", text.strip()


class MeshCoreClient:
    def __init__(self, config, on_message: MessageHandler):
        self.mc_cfg = config.meshcore
        self.resp_cfg = config.response
        self.on_message = on_message
        self.connection_lost = threading.Event()
        self._mc: Optional[MeshCore] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._room_pubkey: Optional[str] = None  # set after successful room login
        self._closing = False

    def connect(self, retries: int = 10, retry_delay: float = 15.0):
        self._loop = asyncio.new_event_loop()
        loop_ready = threading.Event()

        def run_loop():
            asyncio.set_event_loop(self._loop)
            self._loop.call_soon(loop_ready.set)
            self._loop.run_forever()

        self._thread = threading.Thread(target=run_loop, daemon=True, name="meshcore-loop")
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
                if self._mc is None:
                    raise RuntimeError("device did not respond")
                self._mc.subscribe(EventType.CONTACT_MSG_RECV, self._on_contact_message)
                self._mc.subscribe(EventType.DISCONNECTED, self._on_disconnected)
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

    async def _on_disconnected(self, event):
        reason = (event.payload or {}).get("reason", "unknown")
        if self._closing or reason == "manual_disconnect":
            return
        logger.error("Lost connection to MeshCore device %s (%s)", self.mc_cfg.device, reason)
        self.connection_lost.set()

    def disconnect(self):
        self._closing = True
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
        self._room_pubkey = _contact_key(contact)
        commands = self._mc.commands
        if hasattr(commands, "send_login_sync"):
            ok = await commands.send_login_sync(contact, self.mc_cfg.room_password) is not None
        else:
            result = await commands.send_login(contact, self.mc_cfg.room_password)
            ok = getattr(result, "type", None) != EventType.ERROR
        if ok:
            logger.info(
                f"Joined room server {self.mc_cfg.room_server!r} "
                f"(trigger: {self.mc_cfg.room_trigger!r})"
            )
        else:
            logger.warning("Room server login failed (check room_password)")

    def _is_room_sender(self, sender: str) -> bool:
        return bool(self._room_pubkey) and _keys_match(sender, self._room_pubkey)

    def _reply_fn(self, coro_factory) -> Callable[[str], None]:
        """Wrap an async send so the dispatcher's sender thread can call it synchronously."""
        # Generous bound so a wedged event loop can't hang the sender thread forever.
        timeout = self.resp_cfg.max_chunks * (3 * self.resp_cfg.ack_timeout + self.resp_cfg.chunk_delay) + 60

        def reply(text: str):
            future = asyncio.run_coroutine_threadsafe(coro_factory(text), self._loop)
            future.result(timeout=timeout)

        return reply

    async def _on_contact_message(self, event):
        try:
            payload = event.payload or {}
            text = payload.get("text", "").strip()
            sender = payload.get("pubkey_prefix", "unknown")
            if not text:
                return
            if self._is_room_sender(sender):
                self._handle_room_message(text)
                return
            logger.info("[DM] Message from %s (%d chars)", sender, len(text))
            logger.debug("[DM] %s: %r", sender, text)
            reply = self._reply_fn(lambda answer: self._send_to_contact(answer, sender))
            self.on_message(text, sender, True, reply)
        except Exception as e:
            logger.error(f"Error handling contact message: {e}", exc_info=True)

    def _handle_room_message(self, text: str):
        name, message = _split_sender(text)

        trigger = self.mc_cfg.room_trigger
        if not message.startswith(trigger):
            return

        question = message[len(trigger):].strip()
        if not question:
            return

        sender = f"room:{name or 'unknown'}"
        logger.info("[ROOM] Question from %s (%d chars)", sender, len(question))
        logger.debug("[ROOM] question: %r", question)
        room = self._room_pubkey
        reply = self._reply_fn(lambda answer: self._send_to_contact(answer, room))
        self.on_message(question, sender, False, reply)

    async def _on_channel_message(self, event):
        try:
            payload = event.payload or {}
            if payload.get("channel_idx", self.mc_cfg.channel_index) != self.mc_cfg.channel_index:
                return
            name, text = _split_sender(payload.get("text", ""))
            if not text:
                return
            sender = f"ch:{name or payload.get('pubkey_prefix', 'unknown')}"
            logger.info("[CH] Message from %s (%d chars)", sender, len(text))
            logger.debug("[CH] %s: %r", sender, text)
            reply = self._reply_fn(self._send_to_channel)
            self.on_message(text, sender, False, reply)
        except Exception as e:
            logger.error(f"Error handling channel message: {e}", exc_info=True)

    async def _find_contact(self, pubkey_prefix: str):
        result = await self._mc.commands.get_contacts()
        contacts = getattr(result, "payload", None)
        if not contacts or getattr(result, "type", None) == EventType.ERROR:
            return None
        if isinstance(contacts, dict):
            for public_key, contact in contacts.items():
                if _keys_match(_contact_key(contact) or public_key, pubkey_prefix):
                    return contact
            return None

        for contact in contacts:
            if _keys_match(_contact_key(contact), pubkey_prefix):
                return contact
        return None

    async def _send_to_contact(self, text: str, pubkey_prefix: str):
        contact = await self._find_contact(pubkey_prefix)
        if not contact:
            logger.warning(f"No contact found for pubkey prefix {pubkey_prefix!r}")
            return
        commands = self._mc.commands
        if hasattr(commands, "send_msg_with_retry"):
            # Retries and waits for the ACK; returns None if none arrived.
            async def send(part):
                if await commands.send_msg_with_retry(contact, part) is None:
                    logger.warning("No ACK for part to %s — continuing", pubkey_prefix)
            await self._send_chunks(text, send, acked=True)
        else:
            await self._send_chunks(text, lambda part: commands.send_msg(contact, part), acked=False)

    async def _send_to_channel(self, text: str):
        idx = self.mc_cfg.channel_index
        await self._send_chunks(
            text, lambda part: self._mc.commands.send_chan_msg(idx, part), acked=False
        )

    async def _send_chunks(self, text: str, send_fn, acked: bool):
        max_size = min(self.resp_cfg.max_chunk_size, MESHCORE_MAX_CHUNK)
        parts = chunk_text(text, max_size, max_chunks=self.resp_cfg.max_chunks)
        total = len(parts)
        for i, part in enumerate(parts):
            payload = f"[{i+1}/{total}] {part}" if total > 1 else part
            try:
                result = await send_fn(payload)
                if getattr(result, "type", None) == EventType.ERROR:
                    raise RuntimeError(result.payload)
                logger.info(f"Sent part {i+1}/{total}")
            except Exception as e:
                logger.error(f"Failed to send chunk {i+1}: {e}")
                break
            if i < total - 1:
                await asyncio.sleep(INTER_CHUNK_GAP if acked else self.resp_cfg.chunk_delay)
