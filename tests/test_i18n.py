import discord
from discord import app_commands

from bot.i18n import JSONTranslator


async def _translator() -> JSONTranslator:
    translator = JSONTranslator()
    await translator.load()
    return translator


class TestJSONTranslator:
    async def test_exact_locale(self):
        translator = await _translator()
        result = await translator.translate(
            app_commands.locale_str("x", key="balance_show_self"),
            discord.Locale.french,
            None,
        )
        assert result == "Votre solde : **{balance}**"

    async def test_base_language_fallback(self):
        translator = await _translator()
        for locale in (discord.Locale.american_english, discord.Locale.british_english):
            result = await translator.translate(
                app_commands.locale_str("x", key="balance_show_self"),
                locale,
                None,
            )
            assert result == "Your balance: **{balance}**"

    async def test_unknown_locale_defaults(self):
        translator = await _translator()
        result = await translator.translate(
            app_commands.locale_str("x", key="balance_show_self"),
            discord.Locale.russian,
            None,
        )
        assert result == "Your balance: **{balance}**"

    async def test_missing_key_returns_none(self):
        translator = await _translator()
        result = await translator.translate(
            app_commands.locale_str("x", key="nonexistent_key"),
            discord.Locale.french,
            None,
        )
        assert result is None

    async def test_missing_key_without_key_returns_none(self):
        translator = await _translator()
        result = await translator.translate(
            app_commands.locale_str("no key in extras"),
            discord.Locale.french,
            None,
        )
        assert result is None
