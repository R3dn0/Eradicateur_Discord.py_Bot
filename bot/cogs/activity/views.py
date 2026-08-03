import logging
from datetime import datetime, timedelta

import discord

from bot.cogs.activity.models import Activity
from bot.cogs.activity.render import parse_embed, render_embed, set_activity_field
from bot.main import EradicateurBot
from bot.utils.discord_time import parse_user_time

logger = logging.getLogger("eradicateur_bot.activity")

_EDITABLE_FIELDS = ("title", "description", "date", "location", "stuff")
_MAX_SELECT_OPTIONS = 25


def build_view(
    activity: Activity,
    labels: dict[str, str],
    bot: EradicateurBot,
    locale: discord.Locale,
) -> "ActivityView":
    return ActivityView(activity, labels, bot, locale)


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
        self._labels = labels
        self._bot = bot
        self._locale = locale
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
        embed = render_embed(activity, self._labels)
        view = build_view(activity, self._labels, self._bot, self._locale)
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
        field_key = self.values[0]
        current = getattr(activity, field_key, "")
        modal = FieldEditModal(
            label=view.labels[f"field_{field_key}"],
            value=current,
            field_key=field_key,
            labels=view.labels,
            bot=view.bot,
            locale=view.locale,
        )
        await interaction.response.send_modal(modal)


class ActivityJoinSelect(discord.ui.Select):
    def __init__(self, activity: Activity, placeholder: str) -> None:
        options = []
        for i, slot in enumerate(activity.slots, start=1):
            label = f"#{i} {slot.category}"
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
        for i, slot in enumerate(activity.slots, start=1):
            if uid in slot.players:
                message = await view.bot.translate("activity_already_registered", view.locale)
                await interaction.response.send_message(
                    message.replace("{slot}", str(i)), ephemeral=True
                )
                return
        activity.slots[slot_number - 1].players.append(uid)
        embed = render_embed(activity, view.labels)
        new_view = build_view(activity, view.labels, view.bot, view.locale)
        await interaction.response.defer(ephemeral=True)
        await interaction.message.edit(embed=embed, view=new_view)
        message = await view.bot.translate("activity_joined", view.locale)
        await interaction.followup.send(message.replace("{slot}", str(slot_number)), ephemeral=True)


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
        slot_number = None
        for i, slot in enumerate(activity.slots, start=1):
            if uid in slot.players:
                slot.players.remove(uid)
                slot_number = i
                break
        if slot_number is None:
            message = await view.bot.translate("activity_not_registered", view.locale)
            await interaction.response.send_message(message, ephemeral=True)
            return
        embed = render_embed(activity, view.labels)
        new_view = build_view(activity, view.labels, view.bot, view.locale)
        await interaction.response.defer(ephemeral=True)
        await interaction.message.edit(embed=embed, view=new_view)
        message = await view.bot.translate("activity_left", view.locale)
        await interaction.followup.send(message.replace("{slot}", str(slot_number)), ephemeral=True)


class ActivityCloseButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(custom_id="activity_close", label=label, style=discord.ButtonStyle.red)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ActivityView = self.view  # type: ignore[assignment]
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
    ) -> None:
        super().__init__(timeout=None)
        self.activity = activity
        self.labels = labels
        self.bot = bot
        self.locale = locale
        self.add_item(ActivityEditSelect(labels))
        self.add_item(ActivityJoinSelect(activity, labels["join_placeholder"]))
        self.add_item(ActivityQuitButton(labels["quit"]))
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
        self.slots_input = discord.ui.TextInput(
            label=labels["create_slots"],
            placeholder=labels["create_slots_placeholder"],
            required=True,
            style=discord.TextStyle.long,
        )
        self.add_item(self.slots_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        from bot.cogs.activity.render import ensure_fill_slot, parse_slots_text

        slots = parse_slots_text(self.slots_input.value)
        if not slots:
            required_msg = await self.bot.translate("activity_slots_required", self.locale)
            await interaction.response.send_message(required_msg, ephemeral=True)
            return
        slots = ensure_fill_slot(slots)
        activity = Activity(
            title=self.titre_input.value,
            location=self.lieu_input.value,
            stuff=self.stuff_input.value,
            slots=slots,
        )
        view = ActivityDateTimeView(activity, self.labels, self.bot, self.locale)
        title = await self.bot.translate("activity_datetime_title", self.locale)
        await interaction.response.send_message(content=title, view=view)
        try:
            view.message = await interaction.original_response()
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Failed to fetch datetime picker message for guild %s",
                interaction.guild.id,
                exc_info=True,
            )


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


class DateTimeHourSelect(discord.ui.Select):
    def __init__(self, labels: dict[str, str]) -> None:
        now = datetime.now()
        options = [
            discord.SelectOption(label=f"{h:02d}", value=str(h), default=(h == now.hour))
            for h in range(24)
        ]
        super().__init__(placeholder=labels["datetime_hour"], options=options)


class DateTimeMinuteSelect(discord.ui.Select):
    def __init__(self, labels: dict[str, str]) -> None:
        now = datetime.now()
        default_minute = (now.minute // 5) * 5
        options = [
            discord.SelectOption(label=f"{m:02d}", value=str(m), default=(m == default_minute))
            for m in range(0, 60, 5)
        ]
        super().__init__(placeholder=labels["datetime_minute"], options=options)


class DateTimeConfirmButton(discord.ui.Button):
    def __init__(self, label: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ActivityDateTimeView = self.view  # type: ignore[assignment]
        year, month, day = (int(part) for part in view.day_select.values[0].split("-"))
        hour = int(view.hour_select.values[0])
        minute = int(view.minute_select.values[0])
        dt = datetime(year, month, day, hour, minute)
        if dt <= datetime.now():
            message = await view.bot.translate("activity_datetime_past", view.locale)
            await interaction.response.send_message(message, ephemeral=True)
            return
        view.activity.date = f"<t:{int(dt.timestamp())}:F>"
        embed = render_embed(view.activity, view.labels)
        activity_view = build_view(view.activity, view.labels, view.bot, view.locale)
        message = interaction.message
        await interaction.response.edit_message(content=None, embed=embed, view=activity_view)
        try:
            thread_name = f"🪙 {view.activity.title}"[:100]
            await message.create_thread(name=thread_name)
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
        message = await view.bot.translate("activity_datetime_cancelled", view.locale)
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
        self.add_item(DateTimeDaySelect(labels))
        self.add_item(DateTimeHourSelect(labels))
        self.add_item(DateTimeMinuteSelect(labels))
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
