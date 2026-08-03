import discord
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.cogs.activity.models import Activity, Slot
from bot.cogs.activity.render import (
    ensure_fill_slot,
    is_activity_embed,
    parse_embed,
    parse_slots_text,
    render_embed,
)
from bot.cogs.activity.views import ActivityCreateModal, ActivityView
from bot.utils.discord_time import parse_user_time

RENDER_LABELS = {
    "date": "Date",
    "location": "Location",
    "stuff": "Stuff",
}

VIEW_LABELS = {
    "date": "Date",
    "location": "Location",
    "stuff": "Stuff",
    "edit_placeholder": "Edit a field",
    "field_title": "Title",
    "field_description": "Description",
    "field_date": "Date",
    "field_location": "Location",
    "field_stuff": "Stuff",
    "join_placeholder": "Claim a slot",
    "quit": "Leave",
    "close": "Close",
    "create_modal_title": "New activity",
    "create_titre": "Title",
    "create_lieu": "Departure point",
    "create_stuff": "Stuff",
    "create_slots": "Slots",
    "create_slots_placeholder": "placeholder",
    "datetime_title": "Pick the date and time",
    "datetime_day": "Day",
    "datetime_hour": "Hour",
    "datetime_minute": "Minute",
    "datetime_today": "Today",
    "datetime_tomorrow": "Tomorrow",
    "datetime_confirm": "Confirm",
    "datetime_cancel": "Cancel",
    "datetime_cancelled": "Activity creation cancelled.",
    "datetime_past": "That time is already in the past.",
}


def _bot():
    bot = MagicMock()
    bot.translate = AsyncMock(side_effect=lambda key, locale: key)
    return bot


class TestParseSlotsText:
    def test_parses_categories_and_descriptions(self):
        slots = parse_slots_text("🛡️ TANK\n❤️ HEAL - FLEAU\n🗡️ DPS - grande hache Soldat")
        assert [s.category for s in slots] == ["🛡️ TANK", "❤️ HEAL", "🗡️ DPS"]
        assert [s.description for s in slots] == ["", "FLEAU", "grande hache Soldat"]
        assert all(s.players == [] for s in slots)

    def test_parses_prefilled_mentions(self):
        slots = parse_slots_text("DPS - faux <@123> <@456>\nTANK - <@789>")
        assert slots[0].players == [123, 456]
        assert slots[0].description == "faux"
        assert slots[1].players == [789]
        assert slots[1].description == ""

    def test_ignores_blank_lines(self):
        slots = parse_slots_text("TANK\n\n  \nHEAL")
        assert len(slots) == 2

    def test_description_with_hyphens_kept(self):
        slots = parse_slots_text("TANK - MASSE LOUDE ecclé - Gardien - Merce")
        assert slots[0].category == "TANK"
        assert slots[0].description == "MASSE LOUDE ecclé - Gardien - Merce"


class TestEnsureFillSlot:
    def test_appends_fill_when_missing(self):
        slots = ensure_fill_slot([Slot(category="DPS")])
        assert [s.category for s in slots] == ["DPS", "FILL"]

    def test_keeps_existing_fill(self):
        slots = ensure_fill_slot([Slot(category="fill"), Slot(category="DPS")])
        assert [s.category for s in slots] == ["fill", "DPS"]


class TestRenderParseRoundtrip:
    def _activity(self):
        return Activity(
            title="Mob Even",
            description="Let's go",
            date="13h00 UTC",
            location="Bridgewatch portal",
            stuff="T8 equi",
            slots=[
                Slot(category="🛡️ TANK", description="", players=[111]),
                Slot(category="❤️ HEAL", description="FLEAU", players=[222, 333]),
                Slot(category="🗡️ DPS", description="grande hache Soldat"),
            ],
        )

    def test_roundtrip_preserves_activity(self):
        activity = self._activity()
        embed = render_embed(activity, RENDER_LABELS)
        parsed = parse_embed(embed)
        assert parsed.title == activity.title
        assert parsed.description == activity.description
        assert parsed.date == activity.date
        assert parsed.location == activity.location
        assert parsed.stuff == activity.stuff
        assert len(parsed.slots) == 3
        assert parsed.slots[0].category == "🛡️ TANK"
        assert parsed.slots[0].players == [111]
        assert parsed.slots[1].players == [222, 333]
        assert parsed.slots[2].description == "grande hache Soldat"

    def test_slots_globally_numbered(self):
        activity = self._activity()
        embed = render_embed(activity, RENDER_LABELS)
        tank_field = next(f for f in embed.fields if f.name == "🛡️ TANK")
        assert "<@111>" in tank_field.value
        assert "1." in tank_field.value
        heal_field = next(f for f in embed.fields if f.name == "❤️ HEAL")
        assert "2." in heal_field.value
        assert "<@222>" in heal_field.value

    def test_is_activity_embed(self):
        embed = render_embed(self._activity(), RENDER_LABELS)
        assert is_activity_embed(embed) is True
        assert is_activity_embed(discord.Embed(title="other")) is False


class TestActivityView:
    def test_view_built_from_activity(self):
        activity = Activity(title="t", slots=[Slot(category="DPS")])
        view = ActivityView(activity, VIEW_LABELS, _bot(), discord.Locale.american_english)
        assert len(view.children) == 4
        assert view.children[0].custom_id == "activity_edit_field"
        assert view.children[1].custom_id == "activity_join"

    @pytest.mark.asyncio
    async def test_join_select_appends_player(self):
        activity = Activity(title="t", slots=[Slot(category="DPS")])
        bot = _bot()
        view = ActivityView(activity, VIEW_LABELS, bot, discord.Locale.american_english)
        join_select = view.children[1]
        join_select._values = ["1"]

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.user.id = 999
        interaction.message.embeds = [render_embed(activity, RENDER_LABELS)]
        interaction.message.edit = AsyncMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await join_select.callback(interaction)

        edited_embed = interaction.message.edit.call_args.kwargs["embed"]
        parsed = parse_embed(edited_embed)
        assert 999 in parsed.slots[0].players
        interaction.followup.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_join_select_rejects_duplicate(self):
        activity = Activity(title="t", slots=[Slot(category="DPS", players=[999])])
        bot = _bot()
        view = ActivityView(activity, VIEW_LABELS, bot, discord.Locale.american_english)
        join_select = view.children[1]
        join_select._values = ["1"]

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.user.id = 999
        interaction.message.embeds = [render_embed(activity, RENDER_LABELS)]
        interaction.response.send_message = AsyncMock()

        await join_select.callback(interaction)

        interaction.response.send_message.assert_awaited_once()
        interaction.message.edit.assert_not_called()

    @pytest.mark.asyncio
    async def test_quit_button_releases_slot(self):
        activity = Activity(title="t", slots=[Slot(category="DPS", players=[999, 888])])
        bot = _bot()
        view = ActivityView(activity, VIEW_LABELS, bot, discord.Locale.american_english)
        quit_button = view.children[2]

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.user.id = 999
        interaction.message.embeds = [render_embed(activity, RENDER_LABELS)]
        interaction.message.edit = AsyncMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await quit_button.callback(interaction)

        edited_embed = interaction.message.edit.call_args.kwargs["embed"]
        parsed = parse_embed(edited_embed)
        assert parsed.slots[0].players == [888]
        interaction.followup.send.assert_awaited_once()


class TestActivityCog:
    @pytest.fixture
    def cog(self):
        from bot.cogs.activity.cog import ActivityCog

        return ActivityCog(_bot())

    def _thread_interaction(self, embed):
        message = AsyncMock(spec=discord.Message)
        message.embeds = [embed]
        message.edit = AsyncMock()

        parent = MagicMock()
        parent.fetch_message = AsyncMock(return_value=message)

        thread = MagicMock(spec=discord.Thread)
        thread.parent = parent

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.channel = thread
        interaction.guild = MagicMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = 777
        interaction.locale = discord.Locale.american_english
        interaction.response = AsyncMock()
        interaction.response.send_message = AsyncMock()
        return interaction, message

    @pytest.mark.asyncio
    async def test_create_opens_create_modal(self, cog):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.american_english
        interaction.guild = MagicMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.response = AsyncMock()
        interaction.response.send_modal = AsyncMock()

        await cog.create.callback(cog, interaction)

        interaction.response.send_modal.assert_awaited_once()
        modal = interaction.response.send_modal.call_args.args[0]
        assert isinstance(modal, ActivityCreateModal)

    @pytest.mark.asyncio
    async def test_create_modal_submit_posts_embed(self):
        bot = _bot()
        modal = ActivityCreateModal(VIEW_LABELS, bot, discord.Locale.american_english)
        modal.titre_input._value = "Mob Even"
        modal.lieu_input._value = "portal"
        modal.heure_input._value = "20:00"
        modal.stuff_input._value = "T8"
        modal.slots_input._value = "Tank - offtank\nDPS - x2 @dps"
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.guild = MagicMock()
        interaction.guild.id = 1
        message = MagicMock()
        message.create_thread = AsyncMock()
        interaction.original_response = AsyncMock(return_value=message)
        interaction.response.send_message = AsyncMock()

        await modal.on_submit(interaction)

        interaction.response.send_message.assert_awaited_once()
        kwargs = interaction.response.send_message.call_args.kwargs
        embed = kwargs["embed"]
        parsed = parse_embed(embed)
        assert parsed.title == "Mob Even"
        assert parsed.location == "portal"
        assert parsed.stuff == "T8"
        assert parsed.date.startswith("<t:")
        assert len(parsed.slots) == 3
        assert parsed.slots[-1].category == "FILL"
        message.create_thread.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_modal_rejects_empty_slots(self):
        bot = _bot()
        modal = ActivityCreateModal(VIEW_LABELS, bot, discord.Locale.american_english)
        modal.titre_input._value = "Mob Even"
        modal.lieu_input._value = "portal"
        modal.heure_input._value = "20:00"
        modal.slots_input._value = "\n  "
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.send_message = AsyncMock()
        interaction.response.send_modal = AsyncMock()

        await modal.on_submit(interaction)

        interaction.response.send_message.assert_awaited_once()
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
        interaction.response.send_modal.assert_not_called()

    @pytest.mark.asyncio
    async def test_join_in_thread_edits_embed(self, cog):
        activity = Activity(title="t", slots=[Slot(category="DPS")])
        embed = render_embed(activity, RENDER_LABELS)
        interaction, message = self._thread_interaction(embed)

        await cog.join.callback(cog, interaction, slot=1)

        message.edit.assert_awaited_once()
        interaction.response.send_message.assert_awaited_once()
        edited = parse_embed(message.edit.call_args.kwargs["embed"])
        assert 777 in edited.slots[0].players

    @pytest.mark.asyncio
    async def test_join_rejects_out_of_range_slot(self, cog):
        activity = Activity(title="t", slots=[Slot(category="DPS")])
        embed = render_embed(activity, RENDER_LABELS)
        interaction, message = self._thread_interaction(embed)

        await cog.join.callback(cog, interaction, slot=99)

        message.edit.assert_not_called()
        interaction.response.send_message.assert_awaited_once()
        assert "invalid" in interaction.response.send_message.call_args.args[0]

    @pytest.mark.asyncio
    async def test_join_rejects_when_already_registered(self, cog):
        activity = Activity(title="t", slots=[Slot(category="DPS", players=[777])])
        embed = render_embed(activity, RENDER_LABELS)
        interaction, message = self._thread_interaction(embed)

        await cog.join.callback(cog, interaction, slot=1)

        message.edit.assert_not_called()
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_join_outside_thread_rejected(self, cog):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.channel = MagicMock(spec=discord.TextChannel)
        interaction.locale = discord.Locale.american_english
        interaction.guild = MagicMock()
        interaction.user = MagicMock(spec=discord.Member)
        interaction.response = AsyncMock()
        interaction.response.send_message = AsyncMock()

        await cog.join.callback(cog, interaction, slot=1)

        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_leave_releases_user_slot(self, cog):
        activity = Activity(title="t", slots=[Slot(category="DPS", players=[777, 555])])
        embed = render_embed(activity, RENDER_LABELS)
        interaction, message = self._thread_interaction(embed)

        await cog.leave.callback(cog, interaction)

        message.edit.assert_awaited_once()
        edited = parse_embed(message.edit.call_args.kwargs["embed"])
        assert edited.slots[0].players == [555]

    @pytest.mark.asyncio
    async def test_leave_when_not_registered(self, cog):
        activity = Activity(title="t", slots=[Slot(category="DPS")])
        embed = render_embed(activity, RENDER_LABELS)
        interaction, message = self._thread_interaction(embed)

        await cog.leave.callback(cog, interaction)

        message.edit.assert_not_called()
        interaction.response.send_message.assert_awaited_once()


class TestParseUserTime:
    def test_full_date_and_time(self):
        result = parse_user_time("03/08/2026 20:00")
        assert result.startswith("<t:")
        assert result.endswith(":F>")

    def test_french_h_separator(self):
        result = parse_user_time("03/08/2026 20h00")
        assert result.startswith("<t:")

    def test_day_month_without_year(self):
        result = parse_user_time("03/08 20:00")
        assert result.startswith("<t:")

    def test_bare_time_rolls_to_tomorrow_when_past(self):
        result = parse_user_time("00:01")
        assert result.startswith("<t:")

    def test_existing_timestamp_reformatted(self):
        result = parse_user_time("<t:1800000000>")
        assert result == "<t:1800000000:F>"

    def test_unparseable_returns_raw(self):
        assert parse_user_time("not a time") == "not a time"
        assert parse_user_time("") == ""


class TestDiscordFieldLimits:
    def test_modal_placeholders_within_limit(self):
        import json

        for lang in ("en", "fr"):
            with open(f"bot/locales/{lang}.json", encoding="utf-8") as f:
                catalog = json.load(f)
            for key, value in catalog.items():
                if "placeholder" not in key:
                    continue
                assert len(value) <= 100, f"{lang}/{key}: {len(value)} > 100"
                assert len(key) <= 45

    def test_modal_labels_within_limit(self):
        import json

        for lang in ("en", "fr"):
            with open(f"bot/locales/{lang}.json", encoding="utf-8") as f:
                catalog = json.load(f)
            for key, value in catalog.items():
                if "label" in key or "title" in key:
                    assert len(value) <= 45, f"{lang}/{key}: {len(value)} > 45"
