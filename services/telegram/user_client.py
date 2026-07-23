import os
from pathlib import Path

from telethon import TelegramClient


class TelegramUserClient:
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str = "data/telegram_user",
    ):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = str(Path(session_name))
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
        self._started = False

    @classmethod
    def from_env(cls) -> "TelegramUserClient":
        api_id = os.getenv("TG_API_ID") or os.getenv("TELEGRAM_API_ID")
        api_hash = os.getenv("TG_API_HASH") or os.getenv("TELEGRAM_API_HASH")
        session_name = (
            os.getenv("TG_USER_SESSION")
            or os.getenv("TELEGRAM_USER_SESSION")
            or "data/telegram_user"
        )

        if not api_id or not api_hash:
            raise RuntimeError(
                "Telegram user client credentials are missing. "
                "Set TG_API_ID and TG_API_HASH."
            )

        return cls(
            api_id=int(api_id),
            api_hash=api_hash,
            session_name=session_name,
        )

    async def start(self) -> TelegramClient:
        if not self._started:
            await self.client.start()
            self._started = True
            print("[TG USER CLIENT] started")
        return self.client

    async def stop(self) -> None:
        if self._started:
            await self.client.disconnect()
            self._started = False
            print("[TG USER CLIENT] stopped")

    def get_client(self) -> TelegramClient:
        return self.client