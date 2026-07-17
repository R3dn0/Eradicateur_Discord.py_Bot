from bot.utils.discord_time import to_discord_timestamp


class TestToDiscordTimestamp:
    def test_known_input_produces_expected_timestamp(self):
        result = to_discord_timestamp("2026-07-17 07:46:10")
        assert result == "<t:1784274370:f>"

    def test_custom_style(self):
        result = to_discord_timestamp("2024-01-01 00:00:00", style="R")
        assert result == "<t:1704067200:R>"

    def test_epoch_zero(self):
        result = to_discord_timestamp("1970-01-01 00:00:00")
        assert result == "<t:0:f>"
