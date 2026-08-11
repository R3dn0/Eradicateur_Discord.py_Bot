import discord
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from bot.cogs.activity.models import Activity, Slot
from bot.cogs.activity.render import (
    ensure_fill_slot,
    is_activity_embed,
    parse_embed,
    parse_slots_text,
    render_embed,
)
from bot.cogs.activity.views import (
    ActivityCloseButton,
    ActivityCreateModal,
    ActivityDateTimeView,
    ActivityView,
    BuilderDoneButton,
    BuilderSearchButton,
    ManualSlotModal,
    PoolConfirmView,
    PoolMoveSelect,
    PoolPositionSelect,
    PoolReorderDoneButton,
    PoolReorderView,
    PoolSearchModal,
    SlotBuilderView,
    build_view,
)
from bot.utils.discord_time import parse_user_time

RENDER_LABELS = {
    "date": "Date",
    "location": "Location",
    "stuff": "Stuff",
    "slots": "Slots",
}

VIEW_LABELS = {
    "date": "Date",
    "location": "Location",
    "stuff": "Stuff",
    "slots": "Slots",
    "edit_placeholder": "Edit a field",
    "field_title": "Title",
    "field_description": "Description",
    "field_date": "Date",
    "field_location": "Location",
    "field_stuff": "Stuff",
    "field_slots": "Slots",
    "join_placeholder": "Claim a slot",
    "quit": "Leave",
    "close": "Close",
    "create_modal_title": "New activity",
    "create_titre": "Title",
    "create_lieu": "Departure point",
    "create_stuff": "Stuff",
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
    "pool_placeholder": "Add a role from the pool",
    "pool_prev": "← Previous page",
    "pool_next": "Next page →",
    "pool_cancel": "Cancel",
    "pool_reorder_title": "Reorder the pool",
    "pool_reorder_done": "Save",
    "pool_reorder_source_placeholder": "Pick the role to move",
    "pool_reorder_position_placeholder": "Pick the target position",
    "manual_modal_title": "Manual slot",
    "manual_category": "Category",
    "manual_description": "Description (optional)",
    "builder_title": "Compose the slots",
    "builder_slots": "Slots",
    "builder_empty": "No slots yet.",
    "builder_manual": "Manual add",
    "builder_remove": "Remove",
    "builder_back": "Back",
    "builder_reorder": "Reorder",
    "builder_search": "🔍 Search",
    "builder_search_active": "✖",
    "reorder_source_placeholder": "Pick the slot to move",
    "reorder_position_placeholder": "Pick the target position",
    "builder_remove_placeholder": "Pick a slot to remove",
    "search_modal_title": "Search the pool",
    "search_modal_label": "Keyword",
    "search_modal_placeholder": "e.g. incub",
    "pool_search_placeholder": "Results for \"{query}\"",
    "pool_no_results": "No match found in the pool.",
    "builder_done": "Done",
}


def _bot():
    bot = MagicMock()
    bot.translate = AsyncMock(side_effect=lambda key, locale: key)
    return bot


def _find_child(view, custom_id):
    for child in view.children:
        if getattr(child, "custom_id", None) == custom_id:
            return child
    return None


def _inter(user):
    interaction = MagicMock()
    interaction.user = user
    return interaction


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
        assert [s.category for s in slots] == ["DPS", "❓ Fill"]

    def test_moves_existing_fill_last(self):
        slots = ensure_fill_slot([Slot(category="fill"), Slot(category="DPS")])
        assert [s.category for s in slots] == ["DPS", "fill"]

    def test_moves_fill_with_emoji_prefix_last(self):
        slots = ensure_fill_slot([Slot(category="❓ Fill"), Slot(category="DPS")])
        assert [s.category for s in slots] == ["DPS", "❓ Fill"]

    def test_keeps_fill_last_with_players(self):
        fill = Slot(category="❓ Fill", players=[555])
        slots = ensure_fill_slot([Slot(category="DPS"), fill])
        assert [s.category for s in slots] == ["DPS", "❓ Fill"]
        assert slots[-1].players == [555]


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
        assert parsed.slots[0].description == ""
        assert parsed.slots[0].players == [111]
        assert parsed.slots[1].category == "❤️ HEAL"
        assert parsed.slots[1].description == "FLEAU"
        assert parsed.slots[1].players == [222, 333]
        assert parsed.slots[2].category == "🗡️ DPS"
        assert parsed.slots[2].description == "grande hache Soldat"
        assert parsed.slots[2].players == []

    def test_slots_rendered_in_single_roster(self):
        activity = self._activity()
        embed = render_embed(activity, RENDER_LABELS)
        slots_field = next(f for f in embed.fields if f.name == "Slots")
        value = slots_field.value
        assert not value.startswith("```")
        assert "🛡️ TANK -" in value
        assert "FLEAU" in value
        assert "grande hache Soldat" in value
        assert " | " not in value
        assert not any(
            line.strip().startswith(f"{i}.")
            for line in value.splitlines()
            for i in range(1, 10)
        )

    def test_creator_stored_in_embed_field_and_roundtrips(self):
        activity = self._activity()
        activity.creator_id = 4242
        embed = render_embed(activity, RENDER_LABELS)
        creator_field = next(f for f in embed.fields if f.name.startswith("\U0001f451"))
        assert "<@4242>" in creator_field.value
        parsed = parse_embed(embed)
        assert parsed.creator_id == 4242

    def test_date_and_location_not_inline(self):
        embed = render_embed(self._activity(), RENDER_LABELS)
        date_field = next(f for f in embed.fields if f.name.startswith("\U0001f570"))
        location_field = next(f for f in embed.fields if f.name.startswith("\U0001f4cd"))
        assert date_field.inline is False
        assert location_field.inline is False

    def test_is_activity_embed(self):
        embed = render_embed(self._activity(), RENDER_LABELS)
        assert is_activity_embed(embed) is True
        assert is_activity_embed(discord.Embed(title="other")) is False


class TestActivityView:
    def test_view_built_from_activity(self):
        activity = Activity(title="t", slots=[Slot(category="DPS")])
        view = ActivityView(activity, VIEW_LABELS, _bot(), discord.Locale.american_english)
        assert len(view.children) == 2
        assert view.children[0].custom_id == "activity_join"
        assert view.children[1].custom_id == "activity_quit"

    def test_manage_tools_only_for_creator_or_admin(self):
        activity = Activity(title="t", creator_id=7, slots=[Slot(category="DPS")])
        bot = _bot()
        creator = MagicMock()
        creator.id = 7
        admin = MagicMock()
        admin.id = 8
        admin.guild_permissions = MagicMock()
        admin.guild_permissions.administrator = True
        stranger = MagicMock()
        stranger.id = 9
        stranger.guild_permissions = MagicMock()
        stranger.guild_permissions.administrator = False
        close_id = "activity_close"
        edit_id = "activity_edit_field"
        creator_view = build_view(activity, VIEW_LABELS, bot, discord.Locale.american_english, _inter(creator))
        admin_view = build_view(activity, VIEW_LABELS, bot, discord.Locale.american_english, _inter(admin))
        stranger_view = build_view(activity, VIEW_LABELS, bot, discord.Locale.american_english, _inter(stranger))
        for manage_view in (creator_view, admin_view):
            assert _find_child(manage_view, close_id) is not None
            assert _find_child(manage_view, edit_id) is not None
        assert _find_child(stranger_view, close_id) is None
        assert _find_child(stranger_view, edit_id) is None

    @pytest.mark.asyncio
    async def test_join_select_appends_player(self):
        activity = Activity(title="t", slots=[Slot(category="DPS")])
        bot = _bot()
        view = ActivityView(activity, VIEW_LABELS, bot, discord.Locale.american_english)
        join_select = _find_child(view, "activity_join")
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
        join_select = _find_child(view, "activity_join")
        join_select._values = ["1"]

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.user.id = 999
        interaction.message.embeds = [render_embed(activity, RENDER_LABELS)]
        interaction.response.send_message = AsyncMock()

        await join_select.callback(interaction)

        interaction.response.send_message.assert_awaited_once()
        interaction.message.edit.assert_not_called()

    @pytest.mark.asyncio
    async def test_join_select_moves_between_slots(self):
        activity = Activity(
            title="t",
            slots=[Slot(category="TANK", players=[999]), Slot(category="DPS")],
        )
        bot = _bot()
        view = ActivityView(activity, VIEW_LABELS, bot, discord.Locale.american_english)
        join_select = _find_child(view, "activity_join")
        join_select._values = ["2"]

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.user.id = 999
        interaction.message.embeds = [render_embed(activity, RENDER_LABELS)]
        interaction.message.edit = AsyncMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await join_select.callback(interaction)

        edited_embed = interaction.message.edit.call_args.kwargs["embed"]
        parsed = parse_embed(edited_embed)
        assert 999 not in parsed.slots[0].players
        assert 999 in parsed.slots[1].players
        sent = interaction.followup.send.call_args.args[0]
        assert "activity_moved" in sent

    @pytest.mark.asyncio
    async def test_close_button_denied_for_stranger(self):
        activity = Activity(title="t", creator_id=7, slots=[Slot(category="DPS")])
        bot = _bot()
        view = ActivityView(activity, VIEW_LABELS, bot, discord.Locale.american_english)
        close_button = ActivityCloseButton("Close")
        close_button._view = view

        stranger = AsyncMock(spec=discord.Interaction)
        stranger.user.id = 9
        stranger.user.guild_permissions = MagicMock()
        stranger.user.guild_permissions.administrator = False
        stranger.locale = discord.Locale.american_english
        stranger.message.embeds = [render_embed(activity, RENDER_LABELS)]
        stranger.response.send_message = AsyncMock()
        stranger.response.edit_message = AsyncMock()

        await close_button.callback(stranger)

        stranger.response.send_message.assert_awaited_once()
        stranger.response.edit_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_quit_button_releases_slot(self):
        activity = Activity(title="t", slots=[Slot(category="DPS", players=[999, 888])])
        bot = _bot()
        view = ActivityView(activity, VIEW_LABELS, bot, discord.Locale.american_english)
        quit_button = _find_child(view, "activity_quit")

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
    async def test_create_modal_submit_opens_slot_builder(self):
        bot = _bot()
        bot.db_manager = MagicMock()
        bot.db_manager.get_connection = AsyncMock(return_value=MagicMock())
        modal = ActivityCreateModal(VIEW_LABELS, bot, discord.Locale.american_english)
        modal.titre_input._value = "Mob Even"
        modal.lieu_input._value = "portal"
        modal.stuff_input._value = "T8"
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.guild = MagicMock()
        interaction.guild.id = 1
        builder_message = MagicMock()
        builder_message.create_thread = AsyncMock()
        interaction.original_response = AsyncMock(return_value=builder_message)
        interaction.response.send_message = AsyncMock()

        with patch("bot.cogs.activity.views.ActivityPoolRepository") as repo_cls:
            repo = MagicMock()
            repo.get_labels = AsyncMock(return_value=["Tank", "Heal"])
            repo_cls.return_value = repo
            await modal.on_submit(interaction)

        interaction.response.send_message.assert_awaited_once()
        kwargs = interaction.response.send_message.call_args.kwargs
        assert kwargs.get("ephemeral") is True
        assert "embed" in kwargs
        view = kwargs["view"]
        assert isinstance(view, SlotBuilderView)
        assert view.activity.title == "Mob Even"
        assert view.activity.location == "portal"
        assert view.activity.stuff == "T8"
        assert view.pool_labels == ["Tank", "Heal"]
        assert view.message is builder_message
        builder_message.create_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_confirm_posts_embed_and_creates_thread(self):
        bot = _bot()
        activity = Activity(
            title="Mob Even",
            location="portal",
            stuff="T8",
            slots=[Slot(category="Tank")],
        )
        view = ActivityDateTimeView(activity, VIEW_LABELS, bot, discord.Locale.american_english)
        future = datetime.now() + timedelta(days=10)
        view.selected_day = future.strftime("%Y-%m-%d")
        view.selected_hour = "12"
        view.selected_minute = "0"

        message = MagicMock()
        message.create_thread = AsyncMock()
        channel = MagicMock()
        public_message = MagicMock()
        public_message.create_thread = AsyncMock()
        channel.send = AsyncMock(return_value=public_message)
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.message = message
        interaction.channel = channel
        interaction.locale = discord.Locale.american_english
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()

        await view.children[3].callback(interaction)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        channel.send.assert_awaited_once()
        embed = channel.send.call_args.kwargs["embed"]
        parsed = parse_embed(embed)
        assert parsed.title == "Mob Even"
        assert parsed.date.startswith("<t:")
        interaction.edit_original_response.assert_awaited_once()
        public_message.create_thread.assert_awaited_once()
        thread_name = public_message.create_thread.call_args.kwargs["name"]
        assert thread_name.startswith("🪙")

    @pytest.mark.asyncio
    async def test_create_confirm_rejects_past_datetime(self):
        bot = _bot()
        activity = Activity(title="t", slots=[Slot(category="Tank")])
        view = ActivityDateTimeView(activity, VIEW_LABELS, bot, discord.Locale.american_english)
        past = datetime.now() - timedelta(days=1)
        view.selected_day = past.strftime("%Y-%m-%d")
        view.selected_hour = "12"
        view.selected_minute = "0"

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.american_english
        interaction.response.send_message = AsyncMock()
        interaction.response.edit_message = AsyncMock()

        await view.children[3].callback(interaction)

        interaction.response.send_message.assert_awaited_once()
        assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
        interaction.response.edit_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_with_untouched_selects_does_not_crash(self):
        bot = _bot()
        activity = Activity(title="t", slots=[Slot(category="Tank")])
        view = ActivityDateTimeView(activity, VIEW_LABELS, bot, discord.Locale.american_english)

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.american_english
        interaction.response.send_message = AsyncMock()
        interaction.response.edit_message = AsyncMock()

        await view.children[3].callback(interaction)

        interaction.response.send_message.assert_awaited_once()
        interaction.response.edit_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_day_select_stores_selection_and_defers(self):
        bot = _bot()
        activity = Activity(title="t", slots=[Slot(category="Tank")])
        view = ActivityDateTimeView(activity, VIEW_LABELS, bot, discord.Locale.american_english)
        day_select = view.children[0]
        day_select._values = ["2026-09-01"]

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()

        await day_select.callback(interaction)

        assert view.selected_day == "2026-09-01"
        interaction.response.defer.assert_awaited_once()

    def test_builder_preview_empty(self):
        view = SlotBuilderView(
            Activity(title="t"), VIEW_LABELS, _bot(), discord.Locale.american_english, []
        )
        embed = view.preview_embed()
        assert embed.fields[0].value == VIEW_LABELS["builder_empty"]

    @pytest.mark.asyncio
    async def test_pool_select_appends_slot(self):
        activity = Activity(title="t")
        bot = _bot()
        view = SlotBuilderView(
            activity,
            VIEW_LABELS,
            bot,
            discord.Locale.american_english,
            ["🛡️ Tank", "💚 Sancti"],
        )
        select = view.children[0]
        select._values = ["0"]

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.edit_message = AsyncMock()

        await select.callback(interaction)

        assert [s.category for s in activity.slots] == ["🛡️ Tank"]
        interaction.response.edit_message.assert_awaited_once()
        refreshed = interaction.response.edit_message.call_args.kwargs["view"]
        assert isinstance(refreshed, SlotBuilderView)

    @pytest.mark.asyncio
    async def test_pool_select_paginates(self):
        pool = [f"Role {i}" for i in range(30)]
        bot = _bot()
        view = SlotBuilderView(Activity(title="t"), VIEW_LABELS, bot, discord.Locale.american_english, pool)
        select = view.children[0]
        values = [o.value for o in select.options]
        assert len(values) == 24
        assert "__next__" in values
        assert "__prev__" not in values

        select._values = ["__next__"]
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.edit_message = AsyncMock()
        await select.callback(interaction)

        refreshed = interaction.response.edit_message.call_args.kwargs["view"]
        next_select = refreshed.children[0]
        values2 = [o.value for o in next_select.options]
        assert "__prev__" in values2
        assert "__next__" not in values2
        assert len(values2) == 8

    @pytest.mark.asyncio
    async def test_manual_slot_modal_appends_slot(self):
        activity = Activity(title="t")
        bot = _bot()
        view = SlotBuilderView(activity, VIEW_LABELS, bot, discord.Locale.american_english, [])
        modal = ManualSlotModal(VIEW_LABELS, bot, discord.Locale.american_english, view)
        modal.category_input._value = "🧙 Mage"
        modal.description_input._value = "staff"

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()

        await modal.on_submit(interaction)

        assert activity.slots[0].category == "🧙 Mage"
        assert activity.slots[0].description == "staff"
        interaction.response.defer.assert_awaited_once()
        interaction.edit_original_response.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_done_requires_at_least_one_slot(self):
        bot = _bot()
        view = SlotBuilderView(Activity(title="t"), VIEW_LABELS, bot, discord.Locale.american_english, [])
        done = next(c for c in view.children if isinstance(c, BuilderDoneButton))

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.american_english
        interaction.response.send_message = AsyncMock()

        await done.callback(interaction)

        interaction.response.send_message.assert_awaited_once()
        interaction.response.edit_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_done_opens_datetime_picker_and_appends_fill(self):
        activity = Activity(title="t", slots=[Slot(category="Tank")])
        bot = _bot()
        view = SlotBuilderView(activity, VIEW_LABELS, bot, discord.Locale.american_english, [])
        done = next(c for c in view.children if isinstance(c, BuilderDoneButton))

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.american_english
        message = MagicMock()
        interaction.message = message
        interaction.response.edit_message = AsyncMock()

        await done.callback(interaction)

        interaction.response.edit_message.assert_awaited_once()
        datetime_view = interaction.response.edit_message.call_args.kwargs["view"]
        assert isinstance(datetime_view, ActivityDateTimeView)
        assert datetime_view.message is message
        assert [s.category for s in activity.slots] == ["Tank", "❓ Fill"]

    @pytest.mark.asyncio
    async def test_builder_remove_button_enters_remove_mode_and_removes_slots(self):
        activity = Activity(title="t", slots=[Slot(category="Tank"), Slot(category="Heal")])
        bot = _bot()
        view = SlotBuilderView(activity, VIEW_LABELS, bot, discord.Locale.american_english, [])
        remove = view.children[2]
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.edit_message = AsyncMock()

        await remove.callback(interaction)

        refreshed = interaction.response.edit_message.call_args.kwargs["view"]
        assert refreshed.mode == "remove"
        select = refreshed.children[0]
        assert isinstance(select, discord.ui.Select)
        assert [o.value for o in select.options] == ["0", "1"]

        select._values = ["0"]
        interaction.response.edit_message.reset_mock()
        await select.callback(interaction)

        refreshed = interaction.response.edit_message.call_args.kwargs["view"]
        assert refreshed.mode == "remove"
        assert [s.category for s in activity.slots] == ["Heal"]
        select = refreshed.children[0]
        assert [o.value for o in select.options] == ["0"]

        select._values = ["0"]
        interaction.response.edit_message.reset_mock()
        await select.callback(interaction)

        refreshed = interaction.response.edit_message.call_args.kwargs["view"]
        assert refreshed.mode == "add"
        assert activity.slots == []

    @pytest.mark.asyncio
    async def test_builder_back_button_returns_to_add_mode(self):
        activity = Activity(title="t", slots=[Slot(category="Tank")])
        bot = _bot()
        view = SlotBuilderView(activity, VIEW_LABELS, bot, discord.Locale.american_english, [])
        remove = view.children[2]
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.edit_message = AsyncMock()

        await remove.callback(interaction)
        refreshed = interaction.response.edit_message.call_args.kwargs["view"]
        assert refreshed.mode == "remove"

        interaction.response.edit_message.reset_mock()
        await refreshed.children[1].callback(interaction)

        refreshed = interaction.response.edit_message.call_args.kwargs["view"]
        assert refreshed.mode == "add"
        assert isinstance(refreshed.children[0], discord.ui.Select)

    @pytest.mark.asyncio
    async def test_builder_reorder_button_enters_reorder_mode(self):
        activity = Activity(
            title="t", slots=[Slot(category="A"), Slot(category="B"), Slot(category="C")]
        )
        bot = _bot()
        view = SlotBuilderView(activity, VIEW_LABELS, bot, discord.Locale.american_english, [])
        reorder = view.children[3]
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.edit_message = AsyncMock()

        await reorder.callback(interaction)

        refreshed = interaction.response.edit_message.call_args.kwargs["view"]
        assert refreshed.mode == "reorder"
        move, position = refreshed.children[0], refreshed.children[1]
        assert isinstance(move, discord.ui.Select)
        assert isinstance(position, discord.ui.Select)
        assert position.disabled is True
        assert [o.value for o in move.options] == ["0", "1", "2"]
        assert [o.value for o in position.options] == ["1", "2", "3"]

    @pytest.mark.asyncio
    async def test_builder_reorder_moves_slot(self):
        activity = Activity(
            title="t", slots=[Slot(category="A"), Slot(category="B"), Slot(category="C")]
        )
        bot = _bot()
        view = SlotBuilderView(activity, VIEW_LABELS, bot, discord.Locale.american_english, [])
        reorder = view.children[3]
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.edit_message = AsyncMock()

        await reorder.callback(interaction)
        refreshed = interaction.response.edit_message.call_args.kwargs["view"]
        move = refreshed.children[0]
        move._values = ["0"]
        await move.callback(interaction)

        assert refreshed.source_index == 0
        assert refreshed.position_select.disabled is False
        position = refreshed.children[1]
        assert position.disabled is False

        position._values = ["3"]
        interaction.response.edit_message.reset_mock()
        await position.callback(interaction)

        assert [s.category for s in activity.slots] == ["B", "C", "A"]
        refreshed = interaction.response.edit_message.call_args.kwargs["view"]
        assert refreshed.mode == "reorder"
        assert refreshed.position_select.disabled is True

    @pytest.mark.asyncio
    async def test_builder_reorder_same_position_is_noop(self):
        activity = Activity(
            title="t", slots=[Slot(category="A"), Slot(category="B"), Slot(category="C")]
        )
        bot = _bot()
        view = SlotBuilderView(activity, VIEW_LABELS, bot, discord.Locale.american_english, [])
        reorder = view.children[3]
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.edit_message = AsyncMock()

        await reorder.callback(interaction)
        refreshed = interaction.response.edit_message.call_args.kwargs["view"]
        move = refreshed.children[0]
        move._values = ["1"]
        await move.callback(interaction)
        position = refreshed.children[1]
        position._values = ["2"]
        await position.callback(interaction)

        assert [s.category for s in activity.slots] == ["A", "B", "C"]

    @pytest.mark.asyncio
    async def test_builder_reorder_ignored_with_less_than_two_slots(self):
        activity = Activity(title="t", slots=[Slot(category="A")])
        bot = _bot()
        view = SlotBuilderView(activity, VIEW_LABELS, bot, discord.Locale.american_english, [])
        reorder = view.children[3]
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.edit_message = AsyncMock()

        await reorder.callback(interaction)

        interaction.response.edit_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_builder_search_button_opens_modal(self):
        activity = Activity(title="t")
        bot = _bot()
        view = SlotBuilderView(activity, VIEW_LABELS, bot, discord.Locale.american_english, [])
        search = next(c for c in view.children if isinstance(c, BuilderSearchButton))
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.send_modal = AsyncMock()

        await search.callback(interaction)

        modal = interaction.response.send_modal.call_args.args[0]
        assert isinstance(modal, PoolSearchModal)

    @pytest.mark.asyncio
    async def test_builder_search_filters_pool(self):
        pool = ["🛡️ Tank incub", "❤️ Heal", "🗡️ DPS grande hache"]
        activity = Activity(title="t")
        bot = _bot()
        view = SlotBuilderView(activity, VIEW_LABELS, bot, discord.Locale.american_english, pool)
        modal = PoolSearchModal(VIEW_LABELS, bot, discord.Locale.american_english, view)
        modal.query_input._value = "incub"

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.american_english
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()

        await modal.on_submit(interaction)

        refreshed = interaction.edit_original_response.call_args.kwargs["view"]
        assert refreshed.search_query == "incub"
        options = [o.value for o in refreshed.children[0].options]
        assert options == ["0"]
        assert [o.label for o in refreshed.children[0].options] == ["🛡️ Tank incub"]
        assert isinstance(refreshed.children[4], BuilderSearchButton)

    @pytest.mark.asyncio
    async def test_builder_search_filters_and_adds_matching_role(self):
        pool = ["🛡️ Tank incub", "❤️ Heal", "🗡️ DPS"]
        activity = Activity(title="t")
        bot = _bot()
        view = SlotBuilderView(activity, VIEW_LABELS, bot, discord.Locale.american_english, pool)
        modal = PoolSearchModal(VIEW_LABELS, bot, discord.Locale.american_english, view)
        modal.query_input._value = "incub"
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.american_english
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()

        await modal.on_submit(interaction)
        refreshed = interaction.edit_original_response.call_args.kwargs["view"]
        select = refreshed.children[0]
        select._values = ["0"]
        interaction.response.edit_message = AsyncMock()
        await select.callback(interaction)

        assert [s.category for s in activity.slots] == ["🛡️ Tank incub"]
        refreshed = interaction.response.edit_message.call_args.kwargs["view"]
        assert refreshed.search_query is None
        assert len(refreshed.children[0].options) == 3

    @pytest.mark.asyncio
    async def test_builder_search_no_results_shows_error(self):
        pool = ["🛡️ Tank incub"]
        activity = Activity(title="t")
        bot = _bot()
        view = SlotBuilderView(activity, VIEW_LABELS, bot, discord.Locale.american_english, pool)
        modal = PoolSearchModal(VIEW_LABELS, bot, discord.Locale.american_english, view)
        modal.query_input._value = "zzz"

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.american_english
        interaction.response.send_message = AsyncMock()

        await modal.on_submit(interaction)

        interaction.response.send_message.assert_awaited_once()
        assert view.search_query is None

    @pytest.mark.asyncio
    async def test_builder_search_empty_query_clears_filter(self):
        pool = ["🛡️ Tank incub", "❤️ Heal"]
        activity = Activity(title="t")
        bot = _bot()
        view = SlotBuilderView(
            activity, VIEW_LABELS, bot, discord.Locale.american_english, pool, search_query="heal"
        )
        modal = PoolSearchModal(VIEW_LABELS, bot, discord.Locale.american_english, view)
        modal.query_input._value = ""

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.american_english
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()

        await modal.on_submit(interaction)

        refreshed = interaction.edit_original_response.call_args.kwargs["view"]
        assert refreshed.search_query is None
        assert len(refreshed.children[0].options) == 2

    @pytest.mark.asyncio
    async def test_edit_select_opens_slot_builder_for_slots(self):
        activity = Activity(title="t", creator_id=7, slots=[Slot(category="Tank")])
        bot = _bot()
        view = build_view(
            activity, VIEW_LABELS, bot, discord.Locale.american_english, _inter(MagicMock(id=7))
        )
        edit_select = _find_child(view, "activity_edit_field")
        edit_select._values = ["slots"]
        embed = render_embed(activity, VIEW_LABELS)
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.message.embeds = [embed]
        interaction.locale = discord.Locale.american_english
        interaction.user = MagicMock()
        interaction.user.id = 7
        interaction.guild = None
        interaction.response.send_message = AsyncMock()

        await edit_select.callback(interaction)

        builder = interaction.response.send_message.call_args.kwargs["view"]
        assert isinstance(builder, SlotBuilderView)
        assert builder.mode == "add"
        assert builder._on_done is not None

    @pytest.mark.asyncio
    async def test_builder_edit_done_updates_public_embed_and_keeps_players(self):
        activity = Activity(title="t", creator_id=7, slots=[Slot(category="🛡️ Tank", players=[111])])
        bot = _bot()
        view = build_view(
            activity, VIEW_LABELS, bot, discord.Locale.american_english, _inter(MagicMock(id=7))
        )
        edit_select = _find_child(view, "activity_edit_field")
        edit_select._values = ["slots"]
        embed = render_embed(activity, VIEW_LABELS)
        public_message = MagicMock()
        public_message.embeds = [embed]
        public_message.edit = AsyncMock()
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.message = public_message
        interaction.locale = discord.Locale.american_english
        interaction.user = MagicMock()
        interaction.user.id = 7
        interaction.guild = None
        interaction.response.send_message = AsyncMock()

        await edit_select.callback(interaction)
        builder = interaction.response.send_message.call_args.kwargs["view"]
        done = next(
            c
            for c in builder.children
            if isinstance(c, BuilderDoneButton)
        )

        done_interaction = AsyncMock(spec=discord.Interaction)
        done_interaction.locale = discord.Locale.american_english
        done_interaction.user = MagicMock()
        done_interaction.user.id = 7
        done_interaction.response.defer = AsyncMock()
        done_interaction.edit_original_response = AsyncMock()

        await done.callback(done_interaction)

        public_message.edit.assert_awaited_once()
        done_interaction.edit_original_response.assert_awaited_once()
        updated_embed = public_message.edit.call_args.kwargs["embed"]
        parsed = parse_embed(updated_embed)
        assert [s.category for s in parsed.slots] == ["🛡️ Tank", "❓ Fill"]
        assert parsed.slots[0].players == [111]
        assert parsed.slots[0].category == "🛡️ Tank"

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
    async def test_join_moves_between_slots(self, cog):
        activity = Activity(
            title="t",
            slots=[Slot(category="TANK", players=[777]), Slot(category="DPS")],
        )
        embed = render_embed(activity, RENDER_LABELS)
        interaction, message = self._thread_interaction(embed)

        await cog.join.callback(cog, interaction, slot=2)

        message.edit.assert_awaited_once()
        edited = parse_embed(message.edit.call_args.kwargs["embed"])
        assert 777 not in edited.slots[0].players
        assert 777 in edited.slots[1].players
        assert "activity_moved" in interaction.response.send_message.call_args.args[0]

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

    def _pool_interaction(self, cog):
        bot = _bot()
        bot.db_manager = MagicMock()
        bot.db_manager.get_connection = AsyncMock(return_value=MagicMock())
        cog.bot = bot
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.guild = MagicMock()
        interaction.guild.id = 1
        interaction.locale = discord.Locale.american_english
        interaction.response = AsyncMock()
        interaction.response.send_message = AsyncMock()
        return interaction

    @pytest.mark.asyncio
    async def test_pool_add_appends_label(self, cog):
        interaction = self._pool_interaction(cog)
        with patch("bot.cogs.activity.cog.ActivityPoolRepository") as repo_cls:
            repo = MagicMock()
            repo.add_label = AsyncMock()
            repo_cls.return_value = repo
            await cog.pool_add.callback(cog, interaction, label="🛡️ Tank")

        repo.add_label.assert_awaited_once_with(1, "🛡️ Tank")
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pool_add_rejects_empty_label(self, cog):
        interaction = self._pool_interaction(cog)
        await cog.pool_add.callback(cog, interaction, label="   ")
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pool_show_lists_labels(self, cog):
        interaction = self._pool_interaction(cog)
        with patch("bot.cogs.activity.cog.ActivityPoolRepository") as repo_cls:
            repo = MagicMock()
            repo.get_labels = AsyncMock(return_value=["A", "B"])
            repo_cls.return_value = repo
            await cog.pool_show.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert "1. A" in embed.description
        assert "2. B" in embed.description

    @pytest.mark.asyncio
    async def test_pool_remove_shows_confirm(self, cog):
        interaction = self._pool_interaction(cog)
        cog.bot.translate = AsyncMock(
            side_effect=lambda key, locale: (
                "Remove {position} ({label})?" if key == "activity_pool_remove_confirm" else key
            )
        )
        with patch("bot.cogs.activity.cog.ActivityPoolRepository") as repo_cls:
            repo = MagicMock()
            repo.get_labels = AsyncMock(return_value=["A", "B", "C"])
            repo.remove_position = AsyncMock(return_value=True)
            repo_cls.return_value = repo
            await cog.pool_remove.callback(cog, interaction, position=2)

        repo.remove_position.assert_not_called()
        interaction.response.send_message.assert_awaited_once()
        kwargs = interaction.response.send_message.call_args.kwargs
        assert kwargs.get("ephemeral") is True
        content = interaction.response.send_message.call_args.args[0]
        assert "2" in content
        assert "B" in content
        assert isinstance(kwargs["view"], PoolConfirmView)

    @pytest.mark.asyncio
    async def test_pool_remove_out_of_range_position(self, cog):
        interaction = self._pool_interaction(cog)
        with patch("bot.cogs.activity.cog.ActivityPoolRepository") as repo_cls:
            repo = MagicMock()
            repo.get_labels = AsyncMock(return_value=["A"])
            repo_cls.return_value = repo
            await cog.pool_remove.callback(cog, interaction, position=5)

        interaction.response.send_message.assert_awaited_once()
        assert "view" not in interaction.response.send_message.call_args.kwargs

    @pytest.mark.asyncio
    async def test_pool_remove_invalid_position(self, cog):
        interaction = self._pool_interaction(cog)
        with patch("bot.cogs.activity.cog.ActivityPoolRepository") as repo_cls:
            repo = MagicMock()
            repo.remove_position = AsyncMock(return_value=False)
            repo_cls.return_value = repo
            await cog.pool_remove.callback(cog, interaction, position=0)

        repo.remove_position.assert_not_called()
        interaction.response.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pool_do_remove_removes(self, cog):
        interaction = self._pool_interaction(cog)
        interaction.response.edit_message = AsyncMock()
        with patch("bot.cogs.activity.cog.ActivityPoolRepository") as repo_cls:
            repo = MagicMock()
            repo.remove_position = AsyncMock(return_value=True)
            repo_cls.return_value = repo
            await cog._pool_do_remove(interaction, 2)

        repo.remove_position.assert_awaited_once_with(1, 2)
        interaction.response.edit_message.assert_awaited_once()
        assert interaction.response.edit_message.call_args.kwargs.get("view") is None

    @pytest.mark.asyncio
    async def test_pool_clear_shows_confirm(self, cog):
        interaction = self._pool_interaction(cog)
        await cog.pool_clear.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        kwargs = interaction.response.send_message.call_args.kwargs
        assert isinstance(kwargs["view"], PoolConfirmView)

    @pytest.mark.asyncio
    async def test_pool_do_clear_clears(self, cog):
        interaction = self._pool_interaction(cog)
        interaction.response.edit_message = AsyncMock()
        with patch("bot.cogs.activity.cog.ActivityPoolRepository") as repo_cls:
            repo = MagicMock()
            repo.clear = AsyncMock()
            repo_cls.return_value = repo
            await cog._pool_do_clear(interaction)

        repo.clear.assert_awaited_once_with(1)
        interaction.response.edit_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pool_confirm_view_runs_on_confirm(self):
        called = False

        async def on_confirm(interaction):
            nonlocal called
            called = True

        view = PoolConfirmView("Confirm", "Cancel", on_confirm)
        confirm_button = view.children[0]
        interaction = AsyncMock(spec=discord.Interaction)
        await confirm_button.callback(interaction)
        assert called is True

    @pytest.mark.asyncio
    async def test_pool_confirm_view_cancel_disables(self):
        view = PoolConfirmView(
            "Confirm", "Cancel", on_confirm=lambda interaction: None
        )
        cancel_button = view.children[1]
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.american_english
        interaction.client = MagicMock()
        interaction.client.translate = AsyncMock(return_value="cancelled")
        interaction.response.edit_message = AsyncMock()
        await cancel_button.callback(interaction)
        interaction.response.edit_message.assert_awaited_once()
        assert all(child.disabled for child in view.children)

    @pytest.mark.asyncio
    async def test_pool_reorder_view_moves_label(self):
        bot = _bot()
        view = PoolReorderView(
            VIEW_LABELS, bot, discord.Locale.american_english, ["A", "B", "C"]
        )
        move = view.children[0]
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response.edit_message = AsyncMock()

        move._values = ["0"]
        await move.callback(interaction)
        assert view.source_index == 0
        assert view.position_select.disabled is False

        position = view.children[1]
        position._values = ["3"]
        interaction.response.edit_message.reset_mock()
        await position.callback(interaction)

        assert view.pool_labels == ["B", "C", "A"]
        assert "1. B" in interaction.response.edit_message.call_args.kwargs["embed"].description

    @pytest.mark.asyncio
    async def test_pool_reorder_done_saves_order(self):
        bot = _bot()
        bot.db_manager = MagicMock()
        bot.db_manager.get_connection = AsyncMock(return_value=MagicMock())
        view = PoolReorderView(
            VIEW_LABELS, bot, discord.Locale.american_english, ["A", "B", "C"]
        )
        view.pool_labels = ["B", "C", "A"]
        done = next(c for c in view.children if isinstance(c, PoolReorderDoneButton))
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.locale = discord.Locale.american_english
        interaction.guild = MagicMock()
        interaction.guild.id = 1
        interaction.response.edit_message = AsyncMock()

        with patch("bot.cogs.activity.views.ActivityPoolRepository") as repo_cls:
            repo = MagicMock()
            repo.set_order = AsyncMock()
            repo_cls.return_value = repo
            await done.callback(interaction)

        repo.set_order.assert_awaited_once_with(1, ["B", "C", "A"])
        interaction.response.edit_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pool_reorder_command_opens_view(self, cog):
        interaction = self._pool_interaction(cog)
        with patch("bot.cogs.activity.cog.ActivityPoolRepository") as repo_cls:
            repo = MagicMock()
            repo.get_labels = AsyncMock(return_value=["A", "B", "C"])
            repo_cls.return_value = repo
            await cog.pool_reorder.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        view = interaction.response.send_message.call_args.kwargs["view"]
        assert isinstance(view, PoolReorderView)
        assert isinstance(view.children[0], PoolMoveSelect)
        assert isinstance(view.children[1], PoolPositionSelect)

    @pytest.mark.asyncio
    async def test_pool_reorder_command_requires_two_roles(self, cog):
        interaction = self._pool_interaction(cog)
        with patch("bot.cogs.activity.cog.ActivityPoolRepository") as repo_cls:
            repo = MagicMock()
            repo.get_labels = AsyncMock(return_value=["A"])
            repo_cls.return_value = repo
            await cog.pool_reorder.callback(cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        assert "view" not in interaction.response.send_message.call_args.kwargs

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

    def test_day_month_rolls_past_date_forward(self):
        result = parse_user_time("01/01 00:00")
        assert result.startswith("<t:")
        assert int(result[3:-3]) > datetime.now().timestamp()

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
