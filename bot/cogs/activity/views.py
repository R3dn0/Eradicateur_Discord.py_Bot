import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import discord

from bot.cogs.activity.models import Activity, Slot
from bot.cogs.activity.render import (
    ensure_fill_slot,
    parse_embed,
    render_embed,
    set_activity_field,
)
from bot.main import EradicateurBot
from bot.repositories.activity_pool_repository import ActivityPoolRepository
from bot.utils.discord_time import parse_user_time

logger = logging.getLogger("eradicateur_bot.activity")

_EDITABLE_FIELDS = ("title", "description", "date", "location", "stuff", "slots")
_MAX_SELECT_OPTIONS = 25
_POOL_PAGE_SIZE = 23

LABEL_KEYS = {
    "date": "activity_date_label",
    "location": "activity_location_label",
    "stuff": "activity_stuff_label",
    "edit_placeholder": "activity_edit_placeholder",
    "field_title": "activity_edit_field_title",
    "field_description": "activity_edit_field_description",
    "field_date": "activity_edit_field_date",
    "field_location": "activity_edit_field_location",
    "field_stuff": "activity_edit_field_stuff",
    "field_slots": "activity_edit_field_slots",
    "join_placeholder": "activity_join_placeholder",
    "quit": "activity_quit_label",
    "close": "activity_close_label",
    "create_modal_title": "activity_create_modal_title",
    "create_titre": "activity_create_modal_titre_label",
    "create_lieu": "activity_create_modal_lieu_label",
    "create_stuff": "activity_create_modal_stuff_label",
    "datetime_title": "activity_datetime_title",
    "datetime_day": "activity_datetime_day",
    "datetime_hour": "activity_datetime_hour",
    "datetime_minute": "activity_datetime_minute",
    "datetime_today": "activity_datetime_today",
    "datetime_tomorrow": "activity_datetime_tomorrow",
    "datetime_confirm": "activity_datetime_confirm",
    "datetime_cancel": "activity_datetime_cancel",
    "datetime_cancelled": "activity_datetime_cancelled",
    "datetime_past": "activity_datetime_past",
    "slots": "activity_slots_label",
    "pool_placeholder": "activity_pool_placeholder",
    "pool_prev": "activity_pool_prev",
    "pool_next": "activity_pool_next",
    "pool_cancel": "activity_pool_cancel",
    "pool_reorder_title": "activity_pool_reorder_title",
    "pool_reorder_done": "activity_pool_reorder_done",
    "pool_reorder_source_placeholder": "activity_pool_reorder_source_placeholder",
    "pool_reorder_position_placeholder": "activity_pool_reorder_position_placeholder",
    "manual_modal_title": "activity_manual_modal_title",
    "manual_category": "activity_manual_category_label",
    "manual_description": "activity_manual_description_label",
    "builder_title": "activity_builder_title",
    "builder_slots": "activity_builder_slots_label",
    "builder_empty": "activity_builder_empty",
    "builder_manual": "activity_builder_manual_button",
    "builder_remove": "activity_builder_remove_button",
    "builder_back": "activity_builder_back_button",
    "builder_reorder": "activity_builder_reorder_button",
    "builder_search": "activity_builder_search_button",
    "builder_search_active": "activity_builder_search_active",
    "reorder_source_placeholder": "activity_reorder_source_placeholder",
    "reorder_position_placeholder": "activity_reorder_position_placeholder",
    "builder_remove_placeholder": "activity_builder_remove_placeholder",
    "builder_done": "activity_builder_done_button",
    "search_modal_title": "activity_search_modal_title",
    "search_modal_label": "activity_search_modal_label",
    "search_modal_placeholder": "activity_search_modal_placeholder",
    "pool_search_placeholder": "activity_pool_search_placeholder",
    "pool_no_results": "activity_pool_no_results",
    "activity_pool_empty": "activity_pool_empty",
}

_FALLBACK_LABELS = {key: key for key in LABEL_KEYS}


async def build_labels(bot: EradicateurBot, locale: discord.Locale) -> dict[str, str]:
    labels = {}
    for label_key, locale_key in LABEL_KEYS.items():
        labels[label_key] = await bot.translate(locale_key, locale)
    return labels


def _can_manage(interaction: discord.Interaction | None, activity: Activity) -> bool:
    if interaction is None:
        return False
    if interaction.user.id == activity.creator_id:
        return True
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions is not None and permissions.administrator)


def build_view(
    activity: Activity,
    labels: dict[str, str],
    bot: EradicateurBot,
    locale: discord.Locale,
    interaction: discord.Interaction | None = None,
) -> "ActivityView":
    return ActivityView(activity, labels, bot, locale, can_manage=_can_manage(interaction, activity))


def make_persistent_view(bot: EradicateurBot) -> "ActivityView":
    return ActivityView(
        Activity(title="", slots=[Slot(category="❓ Fill")]),
        _FALLBACK_LABELS,
        bot,
        discord.Locale.american_english,
        can_manage=True,
    )


class FieldEditModal(discord.ui.Modal):
    def __init__(
        self,
        label: str,
        value: str,
        field_key: str,
        labels: dict[str, str],
        bot: EradicateurBot,
        locale: discord.Locale,
    ) -> None:
        super().__init__(timeout=300, title=label)
        self._field_key = field_key
        self._bot = bot
        self.value_input = discord.ui.TextInput(
            label=label,
            default=value,
            required=True,
            style=discord.TextStyle.long if field_key == "description" else discord.TextStyle.short,
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.message is None or not interaction.message.embeds:
            return
        activity = parse_embed(interaction.message.embeds[0])
        value = self.value_input.value
        if self._field_key == "date":
            value = parse_user_time(value)
        activity = set_activity_field(activity, self._field_key, value)
        labels = await build_labels(self._bot, interaction.locale)
        embed = render_embed(activity, labels)
        view = build_view(activity, labels, self._bot, interaction.locale, interaction)
        await interaction.response.edit_message(embed=embed, view=view)


class ActivityEditSelect(discord.ui.Select):
    def __init__(self, labels: dict[str, str]) -> None:
        options = [
            discord.SelectOption(label=labels[f"field_{key}"], value=key)
            for key in _EDITABLE_FIELDS
        ]
        super().__init__(
            custom_id="activity_edit_field",
            placeholder=labels["edit_placeholder"],
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ActivityView = self.view  # type: ignore[assignment]
        if interaction.message is None or not interaction.message.embeds:
            return
        activity = parse_embed(interaction.message.embeds[0])
        if not _can_manage(interaction, activity):
            message = await view.bot.translate("activity_edit_forbidden", interaction.locale)
            await interaction.response.send_message(message, ephemeral=True)
            return
        field_key = self.values[0]
        labels = await build_labels(view.bot, interaction.locale)
        if field_key == "slots":
            pool_labels: list[str] = []
            if interaction.guild is not None:
                db = await view.bot.db_manager.get_connection(interaction.guild.id)
                pool_labels = await ActivityPoolRepository(db).get_labels(interaction.guild.id)
            builder = SlotBuilderView(
                activity,
                labels,
                view.bot,
                interaction.locale,
                pool_labels,
            )
            public_message = interaction.message

            async def apply_slots(inner: discord.Interaction) -> None:
                assert public_message is not None
                activity = parse_embed(public_message.embeds[0])
                activity.slots = builder.activity.slots
                labels = await build_labels(builder.bot, inner.locale)
                embed = render_embed(activity, labels)
                activity_view = build_view(activity, labels, builder.bot, inner.locale, inner)
                await inner.response.defer(ephemeral=True)
                try:
                    await public_message.edit(embed=embed, view=activity_view)
                except (discord.Forbidden, discord.HTTPException):
                    failed_msg = await builder.bot.translate("activity_edit_failed", inner.locale)
                    await inner.edit_original_response(content=failed_msg, embed=None, view=None)
                    return
                done_msg = await builder.bot.translate("activity_slots_updated", inner.locale)
                await inner.edit_original_response(content=done_msg, embed=None, view=None)

            builder._on_done = apply_slots
            await interaction.response.send_message(
                embed=builder.preview_embed(), view=builder, ephemeral=True
            )
            return
        current = getattr(activity, field_key, "")
        modal = FieldEditModal(
            label=labels[f"field_{field_key}"],
            value=current,
            field_key=field_key,
            labels=labels,
            bot=view.bot,
            locale=interaction.locale,
        )
        await interaction.response.send_modal(modal)


class ActivityJoinSelect(discord.ui.Select):
    def __init__(self, activity: Activity, placeholder: str) -> None:
        options = []
        for i, slot in enumerate(activity.slots, start=1):
            label = slot.category
            if slot.description:
                label = f"{label} - {slot.description}"
            if slot.players:
                label = f"{label} ({len(slot.players)})"
            options.append(discord.SelectOption(label=label[:100], value=str(i)))
        super().__init__(
            custom_id="activity_join",
            placeholder=placeholder,
            options=options[:_MAX_SELECT_OPTIONS],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ActivityView = self.view  # type: ignore[assignment]
        if interaction.message is None or not interaction.message.embeds:
            return
        slot_number = int(self.values[0])
        activity = parse_embed(interaction.message.embeds[0])
        uid = interaction.user.id
        previous = None
        previous_slot = None
        for i, slot in enumerate(activity.slots, start=1):
            if uid in slot.players:
                previous = i
                previous_slot = slot
                break
        if previous is not None:
            if previous == slot_number:
                message = await view.bot.translate(
                    "activity_already_registered", interaction.locale
                )
                name = previous_slot.category
                if previous_slot.description:
                    name = f"{name} - {previous_slot.description}"
                await interaction.response.send_message(
                    message.replace("{slot}", name), ephemeral=True
                )
                return
            activity.slots[previous - 1].players.remove(uid)
        activity.slots[slot_number - 1].players.append(uid)
        labels = await build_labels(view.bot, interaction.locale)
        embed = render_embed(activity, labels)
        new_view = build_view(activity, labels, view.bot, interaction.locale, interaction)
        await interaction.response.defer(ephemeral=True)
        await interaction.message.edit(embed=embed, view=new_view)
        target = activity.slots[slot_number - 1]
        name = target.category
        if target.description:
            name = f"{name} - {target.description}"
        if previous is not None:
            message = await view.bot.translate("activity_moved", interaction.locale)
        else:
            message = await view.bot.translate("activity_joined", interaction.locale)
        await interaction.followup.send(message.replace("{slot}", name), ephemeral=True)


class ActivityQuitButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(
            custom_id="activity_quit", label=label, style=discord.ButtonStyle.secondary
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ActivityView = self.view  # type: ignore[assignment]
        if interaction.message is None or not interaction.message.embeds:
            return
        activity = parse_embed(interaction.message.embeds[0])
        uid = interaction.user.id
        slot = None
        for current_slot in activity.slots:
            if uid in current_slot.players:
                current_slot.players.remove(uid)
                slot = current_slot
                break
        if slot is None:
            message = await view.bot.translate("activity_not_registered", interaction.locale)
            await interaction.response.send_message(message, ephemeral=True)
            return
        labels = await build_labels(view.bot, interaction.locale)
        embed = render_embed(activity, labels)
        new_view = build_view(activity, labels, view.bot, interaction.locale, interaction)
        await interaction.response.defer(ephemeral=True)
        await interaction.message.edit(embed=embed, view=new_view)
        name = slot.category
        if slot.description:
            name = f"{name} - {slot.description}"
        message = await view.bot.translate("activity_left", interaction.locale)
        await interaction.followup.send(message.replace("{slot}", name), ephemeral=True)


class ActivityCloseButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(custom_id="activity_close", label=label, style=discord.ButtonStyle.red)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ActivityView = self.view  # type: ignore[assignment]
        if interaction.message is not None and interaction.message.embeds:
            activity = parse_embed(interaction.message.embeds[0])
            if not _can_manage(interaction, activity):
                message = await view.bot.translate("activity_close_forbidden", interaction.locale)
                await interaction.response.send_message(message, ephemeral=True)
                return
        for child in view.children:
            child.disabled = True
        await interaction.response.edit_message(view=view)


class ActivityView(discord.ui.View):
    def __init__(
        self,
        activity: Activity,
        labels: dict[str, str],
        bot: EradicateurBot,
        locale: discord.Locale,
        *,
        can_manage: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.activity = activity
        self.labels = labels
        self.bot = bot
        self.locale = locale
        if can_manage:
            self.add_item(ActivityEditSelect(labels))
        self.add_item(ActivityJoinSelect(activity, labels["join_placeholder"]))
        self.add_item(ActivityQuitButton(labels["quit"]))
        if can_manage:
            self.add_item(ActivityCloseButton(labels["close"]))


class ActivityCreateModal(discord.ui.Modal):
    def __init__(
        self,
        labels: dict[str, str],
        bot: EradicateurBot,
        locale: discord.Locale,
    ) -> None:
        super().__init__(timeout=600, title=labels["create_modal_title"])
        self.labels = labels
        self.bot = bot
        self.locale = locale
        self.titre_input = discord.ui.TextInput(
            label=labels["create_titre"],
            required=True,
            max_length=100,
        )
        self.add_item(self.titre_input)
        self.lieu_input = discord.ui.TextInput(
            label=labels["create_lieu"],
            required=True,
            max_length=100,
        )
        self.add_item(self.lieu_input)
        self.stuff_input = discord.ui.TextInput(
            label=labels["create_stuff"],
            required=False,
            max_length=100,
        )
        self.add_item(self.stuff_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        activity = Activity(
            title=self.titre_input.value,
            location=self.lieu_input.value,
            stuff=self.stuff_input.value,
            creator_id=interaction.user.id,
        )
        pool_labels: list[str] = []
        if interaction.guild is not None:
            db = await self.bot.db_manager.get_connection(interaction.guild.id)
            pool_labels = await ActivityPoolRepository(db).get_labels(interaction.guild.id)
        view = SlotBuilderView(activity, self.labels, self.bot, self.locale, pool_labels)
        await interaction.response.send_message(
            embed=view.preview_embed(), view=view, ephemeral=True
        )
        try:
            view.message = await interaction.original_response()
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Failed to fetch slot builder message for guild %s",
                interaction.guild.id,
                exc_info=True,
            )


class PoolSlotSelect(discord.ui.Select):
    def __init__(
        self,
        labels: dict[str, str],
        pool_labels: list[str],
        page: int,
        placeholder: str | None = None,
    ) -> None:
        self._pool_labels = pool_labels
        self._page = page
        start = page * _POOL_PAGE_SIZE
        options = []
        for i in range(start, min(start + _POOL_PAGE_SIZE, len(pool_labels))):
            options.append(discord.SelectOption(label=pool_labels[i][:100], value=str(i)))
        if page > 0:
            options.append(discord.SelectOption(label=labels["pool_prev"], value="__prev__"))
        if start + _POOL_PAGE_SIZE < len(pool_labels):
            options.append(discord.SelectOption(label=labels["pool_next"], value="__next__"))
        empty = not options
        if empty:
            options.append(
                discord.SelectOption(label=labels["activity_pool_empty"], value="__empty__")
            )
        super().__init__(
            placeholder=placeholder or labels["pool_placeholder"],
            options=options,
            disabled=empty,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SlotBuilderView = self.view  # type: ignore[assignment]
        value = self.values[0]
        if value == "__prev__":
            view.page -= 1
        elif value == "__next__":
            view.page += 1
        elif value == "__empty__":
            return
        else:
            view.activity.slots.append(Slot(category=self._pool_labels[int(value)]))
            view.search_query = None
            view.page = 0
        await view.refresh(interaction)


class SlotRemoveSelect(discord.ui.Select):
    def __init__(self, labels: dict[str, str], slots: list[Slot], page: int) -> None:
        self._slots = slots
        self._page = page
        start = page * _POOL_PAGE_SIZE
        options = []
        for i in range(start, min(start + _POOL_PAGE_SIZE, len(slots))):
            label = f"{i + 1}. {slots[i].category}"
            if slots[i].description:
                label = f"{label} - {slots[i].description}"
            options.append(discord.SelectOption(label=label[:100], value=str(i)))
        if page > 0:
            options.append(discord.SelectOption(label=labels["pool_prev"], value="__prev__"))
        if start + _POOL_PAGE_SIZE < len(slots):
            options.append(discord.SelectOption(label=labels["pool_next"], value="__next__"))
        super().__init__(placeholder=labels["builder_remove_placeholder"], options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SlotBuilderView = self.view  # type: ignore[assignment]
        value = self.values[0]
        if value == "__prev__":
            view.page -= 1
        elif value == "__next__":
            view.page += 1
        else:
            del view.activity.slots[int(value)]
            max_page = max(0, (len(view.activity.slots) - 1) // _POOL_PAGE_SIZE)
            if view.page > max_page:
                view.page = max_page
        await view.refresh(interaction)


class ManualSlotModal(discord.ui.Modal):
    def __init__(
        self,
        labels: dict[str, str],
        bot: EradicateurBot,
        locale: discord.Locale,
        builder: "SlotBuilderView",
    ) -> None:
        super().__init__(timeout=600, title=labels["manual_modal_title"])
        self.labels = labels
        self.bot = bot
        self.locale = locale
        self.builder = builder
        self.category_input = discord.ui.TextInput(
            label=labels["manual_category"],
            required=True,
            max_length=100,
        )
        self.add_item(self.category_input)
        self.description_input = discord.ui.TextInput(
            label=labels["manual_description"],
            required=False,
            max_length=100,
        )
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        category = self.category_input.value.strip()
        if not category:
            message = await self.bot.translate("activity_slots_required", self.locale)
            await interaction.response.send_message(message, ephemeral=True)
            return
        description = self.description_input.value.strip()
        self.builder.activity.slots.append(Slot(category=category, description=description))
        await interaction.response.defer()
        view = SlotBuilderView(
            self.builder.activity,
            self.builder.labels,
            self.builder.bot,
            self.builder.locale,
            self.builder.pool_labels,
            self.builder.page,
            mode=self.builder.mode,
            search_query=self.builder.search_query,
            on_done=self.builder._on_done,
        )
        embed = view.preview_embed()
        await interaction.edit_original_response(content=None, embed=embed, view=view)


class BuilderManualButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SlotBuilderView = self.view  # type: ignore[assignment]
        modal = ManualSlotModal(view.labels, view.bot, view.locale, view)
        await interaction.response.send_modal(modal)


class BuilderRemoveButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SlotBuilderView = self.view  # type: ignore[assignment]
        if not view.activity.slots:
            return
        view.mode = "remove"
        view.page = 0
        await view.refresh(interaction)


class BuilderBackButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SlotBuilderView = self.view  # type: ignore[assignment]
        view.mode = "add"
        view.page = 0
        view.position_page = 0
        view.source_index = None
        await view.refresh(interaction)


class BuilderReorderButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SlotBuilderView = self.view  # type: ignore[assignment]
        if len(view.activity.slots) < 2:
            return
        view.mode = "reorder"
        view.page = 0
        view.position_page = 0
        view.source_index = None
        await view.refresh(interaction)


class PoolSearchModal(discord.ui.Modal):
    def __init__(
        self,
        labels: dict[str, str],
        bot: EradicateurBot,
        locale: discord.Locale,
        builder: "SlotBuilderView",
    ) -> None:
        super().__init__(timeout=300, title=labels["search_modal_title"])
        self._builder = builder
        self._bot = bot
        self._locale = locale
        self.query_input = discord.ui.TextInput(
            label=labels["search_modal_label"],
            placeholder=labels["search_modal_placeholder"],
            default=builder.search_query or "",
            required=False,
            max_length=30,
        )
        self.add_item(self.query_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query = self.query_input.value.strip()
        if query:
            q = query.casefold()
            matches = [label for label in self._builder.pool_labels if q in label.casefold()]
            if not matches:
                message = await self._bot.translate("activity_pool_no_results", self._locale)
                await interaction.response.send_message(message, ephemeral=True)
                return
        self._builder.search_query = query or None
        self._builder.page = 0
        await interaction.response.defer()
        view = SlotBuilderView(
            self._builder.activity,
            self._builder.labels,
            self._builder.bot,
            self._builder.locale,
            self._builder.pool_labels,
            self._builder.page,
            mode=self._builder.mode,
            search_query=self._builder.search_query,
            on_done=self._builder._on_done,
        )
        embed = view.preview_embed()
        await interaction.edit_original_response(content=None, embed=embed, view=view)


class BuilderSearchButton(discord.ui.Button):
    def __init__(self, label: str, style: discord.ButtonStyle) -> None:
        super().__init__(label=label, style=style)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SlotBuilderView = self.view  # type: ignore[assignment]
        modal = PoolSearchModal(view.labels, view.bot, view.locale, view)
        await interaction.response.send_modal(modal)


class SlotMoveSelect(discord.ui.Select):
    def __init__(self, labels: dict[str, str], slots: list[Slot], page: int) -> None:
        self._slots = slots
        start = page * _POOL_PAGE_SIZE
        options = []
        for i in range(start, min(start + _POOL_PAGE_SIZE, len(slots))):
            label = f"{i + 1}. {slots[i].category}"
            if slots[i].description:
                label = f"{label} - {slots[i].description}"
            options.append(discord.SelectOption(label=label[:100], value=str(i)))
        if page > 0:
            options.append(discord.SelectOption(label=labels["pool_prev"], value="__prev__"))
        if start + _POOL_PAGE_SIZE < len(slots):
            options.append(discord.SelectOption(label=labels["pool_next"], value="__next__"))
        super().__init__(placeholder=labels["reorder_source_placeholder"], options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SlotBuilderView = self.view  # type: ignore[assignment]
        value = self.values[0]
        if value == "__prev__":
            view.page -= 1
            await view.refresh(interaction)
            return
        if value == "__next__":
            view.page += 1
            await view.refresh(interaction)
            return
        view.source_index = int(value)
        if view.position_select is not None:
            view.position_select.disabled = False
        await interaction.response.edit_message(view=view)


class SlotPositionSelect(discord.ui.Select):
    def __init__(self, labels: dict[str, str], slot_count: int, position_page: int) -> None:
        start = position_page * _POOL_PAGE_SIZE
        options = []
        for i in range(start, min(start + _POOL_PAGE_SIZE, slot_count)):
            options.append(discord.SelectOption(label=str(i + 1), value=str(i + 1)))
        if position_page > 0:
            options.append(discord.SelectOption(label=labels["pool_prev"], value="__prev__"))
        if start + _POOL_PAGE_SIZE < slot_count:
            options.append(discord.SelectOption(label=labels["pool_next"], value="__next__"))
        super().__init__(
            placeholder=labels["reorder_position_placeholder"],
            options=options,
            disabled=True,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SlotBuilderView = self.view  # type: ignore[assignment]
        value = self.values[0]
        if value == "__prev__":
            view.position_page -= 1
            await view.refresh(interaction)
            return
        if value == "__next__":
            view.position_page += 1
            await view.refresh(interaction)
            return
        source = view.source_index
        target = int(value) - 1
        if source is not None and target != source:
            slot = view.activity.slots.pop(source)
            view.activity.slots.insert(target, slot)
        view.source_index = None
        view.position_page = 0
        await view.refresh(interaction)


class BuilderDoneButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SlotBuilderView = self.view  # type: ignore[assignment]
        if not view.activity.slots:
            message = await view.bot.translate("activity_slots_required", interaction.locale)
            await interaction.response.send_message(message, ephemeral=True)
            return
        ensure_fill_slot(view.activity.slots)
        if view._on_done is not None:
            await view._on_done(interaction)
            return
        datetime_view = ActivityDateTimeView(view.activity, view.labels, view.bot, view.locale)
        title = await view.bot.translate("activity_datetime_title", view.locale)
        await interaction.response.edit_message(content=title, embed=None, view=datetime_view)
        datetime_view.message = interaction.message


class PoolConfirmView(discord.ui.View):
    def __init__(
        self,
        confirm_label: str,
        cancel_label: str,
        on_confirm: Callable[[discord.Interaction], Awaitable[None]],
    ) -> None:
        super().__init__(timeout=300)
        self._on_confirm = on_confirm
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.label == "confirm":
                    child.label = confirm_label
                elif child.label == "cancel":
                    child.label = cancel_label

    @discord.ui.button(label="confirm", style=discord.ButtonStyle.green)
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._on_confirm(interaction)

    @discord.ui.button(label="cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            child.disabled = True
        message = await interaction.client.translate(  # type: ignore[union-attr]
            "activity_pool_cancelled", interaction.locale
        )
        await interaction.response.edit_message(content=message, view=self)


class PoolMoveSelect(discord.ui.Select):
    def __init__(self, labels: dict[str, str], pool_labels: list[str], page: int) -> None:
        self._pool_labels = pool_labels
        start = page * _POOL_PAGE_SIZE
        options = []
        for i in range(start, min(start + _POOL_PAGE_SIZE, len(pool_labels))):
            options.append(
                discord.SelectOption(label=f"{i + 1}. {pool_labels[i]}"[:100], value=str(i))
            )
        if page > 0:
            options.append(discord.SelectOption(label=labels["pool_prev"], value="__prev__"))
        if start + _POOL_PAGE_SIZE < len(pool_labels):
            options.append(discord.SelectOption(label=labels["pool_next"], value="__next__"))
        super().__init__(placeholder=labels["pool_reorder_source_placeholder"], options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: PoolReorderView = self.view  # type: ignore[assignment]
        value = self.values[0]
        if value == "__prev__":
            view.page -= 1
            await view.refresh(interaction)
            return
        if value == "__next__":
            view.page += 1
            await view.refresh(interaction)
            return
        view.source_index = int(value)
        if view.position_select is not None:
            view.position_select.disabled = False
        await interaction.response.edit_message(view=view)


class PoolPositionSelect(discord.ui.Select):
    def __init__(self, labels: dict[str, str], pool_count: int, position_page: int) -> None:
        start = position_page * _POOL_PAGE_SIZE
        options = []
        for i in range(start, min(start + _POOL_PAGE_SIZE, pool_count)):
            options.append(discord.SelectOption(label=str(i + 1), value=str(i + 1)))
        if position_page > 0:
            options.append(discord.SelectOption(label=labels["pool_prev"], value="__prev__"))
        if start + _POOL_PAGE_SIZE < pool_count:
            options.append(discord.SelectOption(label=labels["pool_next"], value="__next__"))
        super().__init__(
            placeholder=labels["pool_reorder_position_placeholder"],
            options=options,
            disabled=True,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: PoolReorderView = self.view  # type: ignore[assignment]
        value = self.values[0]
        if value == "__prev__":
            view.position_page -= 1
            await view.refresh(interaction)
            return
        if value == "__next__":
            view.position_page += 1
            await view.refresh(interaction)
            return
        source = view.source_index
        target = int(value) - 1
        if source is not None and target != source:
            label = view.pool_labels.pop(source)
            view.pool_labels.insert(target, label)
        view.source_index = None
        view.position_page = 0
        await view.refresh(interaction)


class PoolReorderDoneButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: PoolReorderView = self.view  # type: ignore[assignment]
        assert interaction.guild is not None
        db = await view.bot.db_manager.get_connection(interaction.guild.id)
        repo = ActivityPoolRepository(db)
        await repo.set_order(interaction.guild.id, view.pool_labels)
        text = await view.bot.translate("activity_pool_reordered", interaction.locale)
        await interaction.response.edit_message(content=text, embed=None, view=None)


class PoolReorderCancelButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        for child in self.view.children:  # type: ignore[union-attr]
            child.disabled = True
        message = await interaction.client.translate(  # type: ignore[union-attr]
            "activity_pool_cancelled", interaction.locale
        )
        await interaction.response.edit_message(content=message, view=self.view)


class PoolReorderView(discord.ui.View):
    def __init__(
        self,
        labels: dict[str, str],
        bot: EradicateurBot,
        locale: discord.Locale,
        pool_labels: list[str],
        page: int = 0,
        position_page: int = 0,
    ) -> None:
        super().__init__(timeout=300)
        self.labels = labels
        self.bot = bot
        self.locale = locale
        self.pool_labels = pool_labels
        self.page = page
        self.position_page = position_page
        self.source_index: int | None = None
        position = PoolPositionSelect(labels, len(pool_labels), position_page)
        self.position_select = position
        self.add_item(PoolMoveSelect(labels, pool_labels, page))
        self.add_item(position)
        self.add_item(PoolReorderDoneButton(labels["pool_reorder_done"]))
        self.add_item(PoolReorderCancelButton(labels["pool_cancel"]))

    def embed(self) -> discord.Embed:
        embed = discord.Embed(title=self.labels["pool_reorder_title"], color=0xF1C40F)
        embed.description = "\n".join(
            f"{i}. {label}" for i, label in enumerate(self.pool_labels, start=1)
        )
        return embed

    async def refresh(self, interaction: discord.Interaction) -> None:
        view = PoolReorderView(
            self.labels,
            self.bot,
            self.locale,
            self.pool_labels,
            self.page,
            self.position_page,
        )
        await interaction.response.edit_message(content=None, embed=view.embed(), view=view)


class SlotBuilderView(discord.ui.View):
    def __init__(
        self,
        activity: Activity,
        labels: dict[str, str],
        bot: EradicateurBot,
        locale: discord.Locale,
        pool_labels: list[str],
        page: int = 0,
        mode: str = "add",
        position_page: int = 0,
        search_query: str | None = None,
        on_done: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(timeout=600)
        self.activity = activity
        self.labels = labels
        self.bot = bot
        self.locale = locale
        self.pool_labels = pool_labels
        self.page = page
        self.mode = mode
        self._on_done = on_done
        self.message: discord.Message | None = None
        self.source_index: int | None = None
        self.position_page = position_page
        self.position_select: discord.ui.Select | None = None
        self.search_query = search_query
        if mode == "remove":
            self.add_item(SlotRemoveSelect(labels, activity.slots, page))
            self.add_item(BuilderBackButton(labels["builder_back"]))
            self.add_item(BuilderDoneButton(labels["builder_done"]))
        elif mode == "reorder":
            position = SlotPositionSelect(labels, len(activity.slots), position_page)
            self.position_select = position
            self.add_item(SlotMoveSelect(labels, activity.slots, page))
            self.add_item(position)
            self.add_item(BuilderBackButton(labels["builder_back"]))
            self.add_item(BuilderDoneButton(labels["builder_done"]))
        else:
            displayed = self._filtered_pool()
            placeholder = None
            if search_query:
                placeholder = labels["pool_search_placeholder"].replace(
                    "{query}", search_query
                )
            self.add_item(PoolSlotSelect(labels, displayed, page, placeholder))
            self.add_item(BuilderManualButton(labels["builder_manual"]))
            self.add_item(BuilderRemoveButton(labels["builder_remove"]))
            self.add_item(BuilderReorderButton(labels["builder_reorder"]))
            if search_query:
                shown = search_query[:16] + "…" if len(search_query) > 16 else search_query
                search_label = f"{labels['builder_search_active']} {shown}"
                search_style = discord.ButtonStyle.primary
            else:
                search_label = labels["builder_search"]
                search_style = discord.ButtonStyle.secondary
            self.add_item(BuilderSearchButton(search_label, search_style))
            self.add_item(BuilderDoneButton(labels["builder_done"]))

    def _filtered_pool(self) -> list[str]:
        if not self.search_query:
            return self.pool_labels
        query = self.search_query.casefold()
        return [label for label in self.pool_labels if query in label.casefold()]

    def preview_embed(self) -> discord.Embed:
        embed = discord.Embed(title=self.labels["builder_title"], color=0xF1C40F)
        if not self.activity.slots:
            embed.add_field(
                name=self.labels["builder_slots"],
                value=self.labels["builder_empty"],
                inline=False,
            )
            return embed
        lines = []
        for i, slot in enumerate(self.activity.slots, start=1):
            line = slot.category
            if slot.description:
                line = f"{line} - {slot.description}"
            lines.append(f"{i}. {line}")
        value = "\n".join(lines[:25])
        if len(lines) > 25:
            value += f"\n… (+{len(lines) - 25})"
        embed.add_field(name=self.labels["builder_slots"], value=value, inline=False)
        return embed

    async def refresh(self, interaction: discord.Interaction) -> None:
        if self.mode == "remove" and not self.activity.slots:
            self.mode = "add"
            self.page = 0
        position_page = self.position_page if self.mode == "reorder" else 0
        view = SlotBuilderView(
            self.activity,
            self.labels,
            self.bot,
            self.locale,
            self.pool_labels,
            self.page,
            mode=self.mode,
            position_page=position_page,
            search_query=self.search_query,
            on_done=self._on_done,
        )
        embed = view.preview_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class DateTimeDaySelect(discord.ui.Select):
    def __init__(self, labels: dict[str, str]) -> None:
        today = datetime.now().date()
        options = []
        for i in range(21):
            day = today + timedelta(days=i)
            label = day.strftime("%d/%m")
            if i == 0:
                label = f"{labels['datetime_today']} - {label}"
            elif i == 1:
                label = f"{labels['datetime_tomorrow']} - {label}"
            options.append(
                discord.SelectOption(label=label, value=day.isoformat(), default=(i == 0))
            )
        super().__init__(placeholder=labels["datetime_day"], options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ActivityDateTimeView = self.view  # type: ignore[assignment]
        view.selected_day = self.values[0]
        await interaction.response.defer()


class DateTimeHourSelect(discord.ui.Select):
    def __init__(self, labels: dict[str, str]) -> None:
        now = datetime.now()
        options = [
            discord.SelectOption(label=f"{h:02d}", value=str(h), default=(h == now.hour))
            for h in range(24)
        ]
        super().__init__(placeholder=labels["datetime_hour"], options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ActivityDateTimeView = self.view  # type: ignore[assignment]
        view.selected_hour = self.values[0]
        await interaction.response.defer()


class DateTimeMinuteSelect(discord.ui.Select):
    def __init__(self, labels: dict[str, str]) -> None:
        now = datetime.now()
        default_minute = (now.minute // 5) * 5
        options = [
            discord.SelectOption(label=f"{m:02d}", value=str(m), default=(m == default_minute))
            for m in range(0, 60, 5)
        ]
        super().__init__(placeholder=labels["datetime_minute"], options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ActivityDateTimeView = self.view  # type: ignore[assignment]
        view.selected_minute = self.values[0]
        await interaction.response.defer()


class DateTimeConfirmButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ActivityDateTimeView = self.view  # type: ignore[assignment]
        year, month, day = (int(part) for part in view.selected_day.split("-"))
        hour = int(view.selected_hour)
        minute = int(view.selected_minute)
        dt = datetime(year, month, day, hour, minute)
        if dt <= datetime.now():
            message = await view.bot.translate("activity_datetime_past", interaction.locale)
            await interaction.response.send_message(message, ephemeral=True)
            return
        labels = await build_labels(view.bot, interaction.locale)
        view.activity.date = f"<t:{int(dt.timestamp())}:F>"
        embed = render_embed(view.activity, labels)
        activity_view = build_view(view.activity, labels, view.bot, interaction.locale, interaction)
        await interaction.response.defer(ephemeral=True)
        assert interaction.channel is not None
        try:
            public_message = await interaction.channel.send(embed=embed, view=activity_view)
        except (discord.Forbidden, discord.HTTPException):
            failed_msg = await view.bot.translate(
                "activity_datetime_publish_failed", interaction.locale
            )
            await interaction.edit_original_response(content=failed_msg, embed=None, view=None)
            return
        created_msg = await view.bot.translate("activity_datetime_created", interaction.locale)
        await interaction.edit_original_response(content=created_msg, embed=None, view=None)
        try:
            thread_name = f"🪙 {view.activity.title}"[:100]
            await public_message.create_thread(name=thread_name)
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Failed to create activity thread for guild %s",
                interaction.guild.id,
                exc_info=True,
            )


class DateTimeCancelButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ActivityDateTimeView = self.view  # type: ignore[assignment]
        for child in view.children:
            child.disabled = True
        message = await view.bot.translate("activity_datetime_cancelled", interaction.locale)
        await interaction.response.edit_message(content=message, view=view)


class ActivityDateTimeView(discord.ui.View):
    def __init__(
        self,
        activity: Activity,
        labels: dict[str, str],
        bot: EradicateurBot,
        locale: discord.Locale,
    ) -> None:
        super().__init__(timeout=300)
        self.activity = activity
        self.labels = labels
        self.bot = bot
        self.locale = locale
        self.message: discord.Message | None = None
        now = datetime.now()
        self.selected_day = now.date().isoformat()
        self.selected_hour = str(now.hour)
        self.selected_minute = str((now.minute // 5) * 5)
        self.day_select = DateTimeDaySelect(labels)
        self.hour_select = DateTimeHourSelect(labels)
        self.minute_select = DateTimeMinuteSelect(labels)
        self.add_item(self.day_select)
        self.add_item(self.hour_select)
        self.add_item(self.minute_select)
        self.add_item(DateTimeConfirmButton(labels["datetime_confirm"]))
        self.add_item(DateTimeCancelButton(labels["datetime_cancel"]))

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
