import json
import logging
from pathlib import Path

import discord
from discord import app_commands

logger = logging.getLogger("eradicateur_bot.i18n")

DEFAULT_LOCALE = "en"


class JSONTranslator(app_commands.Translator):
    def __init__(self) -> None:
        self._catalog: dict[str, dict[str, str]] = {}
        self._loaded = False

    async def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        locales_dir = Path(__file__).parent / "locales"
        for path in locales_dir.glob("*.json"):
            locale_tag = path.stem
            with open(path, encoding="utf-8") as f:
                self._catalog[locale_tag] = json.load(f)
            logger.info("Loaded locale: %s (%d keys)", locale_tag, len(self._catalog[locale_tag]))

    async def translate(
        self,
        string: discord.app_commands.locale_str,
        locale: discord.Locale,
        context: discord.app_commands.TranslationContextTypes,
    ) -> str | None:
        key = string.extras.get("key")
        if not key:
            return None

        locale_tag = str(getattr(locale, "value", locale)).lower()
        candidates = (locale_tag, locale_tag.split("-")[0], DEFAULT_LOCALE)
        for tag in candidates:
            catalog = self._catalog.get(tag)
            if catalog is None:
                continue
            value = catalog.get(key)
            if value is not None:
                return value
        for catalog in self._catalog.values():
            value = catalog.get(key)
            if value is not None:
                return value
        return None
