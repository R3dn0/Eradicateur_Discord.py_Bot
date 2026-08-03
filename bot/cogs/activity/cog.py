import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.activity.render import is_activity_embed, parse_embed, render_embed
from bot.cogs.activity.views import ActivityCreateModal, ActivityView
from bot.main import EradicateurBot
from bot.utils.discord_guards import require_guild_member

_LABEL_KEYS = {
    "date": "activity_date_label",
    "location": "activity_location_label",
    "stuff": "activity_stuff_label",
    "edit_placeholder": "activity_edit_placeholder",
    "field_title": "activity_edit_field_title",
    "field_description": "activity_edit_field_description",
    "field_date": "activity_edit_field_date",
    "field_location": "activity_edit_field_location",
    "field_stuff": "activity_edit_field_stuff",
    "join_placeholder": "activity_join_placeholder",
    "quit": "activity_quit_label",
    "close": "activity_close_label",
    "create_modal_title": "activity_create_modal_title",
    "create_titre": "activity_create_modal_titre_label",
    "create_lieu": "activity_create_modal_lieu_label",
    "create_stuff": "activity_create_modal_stuff_label",
    "create_slots": "activity_create_modal_slots_label",
    "create_slots_placeholder": "activity_create_modal_slots_placeholder",
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
}


class ActivityCog(
    commands.GroupCog, group_name=app_commands.locale_str("activity", key="activity_name")
):  # type: ignore[call-arg]
    def __init__(self, bot: EradicateurBot) -> None:
        self.bot = bot

    async def _labels(self, interaction: discord.Interaction) -> dict[str, str]:
        labels = {}
        for label_key, locale_key in _LABEL_KEYS.items():
            labels[label_key] = await self.bot.translate(locale_key, interaction.locale)
        return labels

    @app_commands.command(
        name=app_commands.locale_str("create", key="activity_create_name"),
        description=app_commands.locale_str(
            "Post an activity signup embed with slots",
            key="activity_create_description",
        ),
    )
    @require_guild_member
    async def create(self, interaction: discord.Interaction) -> None:
        labels = await self._labels(interaction)
        modal = ActivityCreateModal(labels, self.bot, interaction.locale)
        await interaction.response.send_modal(modal)

    @app_commands.command(
        name=app_commands.locale_str("join", key="activity_join_name"),
        description=app_commands.locale_str(
            "Claim a slot in the activity", key="activity_join_description"
        ),
    )
    @app_commands.describe(
        slot=app_commands.locale_str(
            "Slot number shown on the embed", key="activity_join_slot_description"
        ),
    )
    async def join(self, interaction: discord.Interaction, slot: int) -> None:
        message = await self._activity_message(interaction)
        if message is None:
            await interaction.response.send_message(
                await self.bot.translate("activity_not_in_thread", interaction.locale),
                ephemeral=True,
            )
            return
        if not message.embeds or not is_activity_embed(message.embeds[0]):
            await interaction.response.send_message(
                await self.bot.translate("activity_not_activity", interaction.locale),
                ephemeral=True,
            )
            return

        activity = parse_embed(message.embeds[0])
        if slot < 1 or slot > len(activity.slots):
            await interaction.response.send_message(
                await self.bot.translate("activity_invalid_slot", interaction.locale),
                ephemeral=True,
            )
            return

        uid = interaction.user.id
        for i, current_slot in enumerate(activity.slots, start=1):
            if uid in current_slot.players:
                text = await self.bot.translate("activity_already_registered", interaction.locale)
                await interaction.response.send_message(
                    text.replace("{slot}", str(i)), ephemeral=True
                )
                return

        activity.slots[slot - 1].players.append(uid)
        labels = await self._labels(interaction)
        embed = render_embed(activity, labels)
        view = ActivityView(activity, labels, self.bot, interaction.locale)
        await message.edit(embed=embed, view=view)
        text = await self.bot.translate("activity_joined", interaction.locale)
        await interaction.response.send_message(text.replace("{slot}", str(slot)), ephemeral=True)

    @app_commands.command(
        name=app_commands.locale_str("leave", key="activity_leave_name"),
        description=app_commands.locale_str("Release your slot", key="activity_leave_description"),
    )
    async def leave(self, interaction: discord.Interaction) -> None:
        message = await self._activity_message(interaction)
        if message is None:
            await interaction.response.send_message(
                await self.bot.translate("activity_not_in_thread", interaction.locale),
                ephemeral=True,
            )
            return
        if not message.embeds or not is_activity_embed(message.embeds[0]):
            await interaction.response.send_message(
                await self.bot.translate("activity_not_activity", interaction.locale),
                ephemeral=True,
            )
            return

        activity = parse_embed(message.embeds[0])
        uid = interaction.user.id
        slot_number = None
        for i, current_slot in enumerate(activity.slots, start=1):
            if uid in current_slot.players:
                current_slot.players.remove(uid)
                slot_number = i
                break
        if slot_number is None:
            await interaction.response.send_message(
                await self.bot.translate("activity_not_registered", interaction.locale),
                ephemeral=True,
            )
            return

        labels = await self._labels(interaction)
        embed = render_embed(activity, labels)
        view = ActivityView(activity, labels, self.bot, interaction.locale)
        await message.edit(embed=embed, view=view)
        text = await self.bot.translate("activity_left", interaction.locale)
        await interaction.response.send_message(
            text.replace("{slot}", str(slot_number)), ephemeral=True
        )

    async def _activity_message(self, interaction: discord.Interaction) -> discord.Message | None:
        channel = interaction.channel
        if not isinstance(channel, discord.Thread):
            return None
        parent = channel.parent
        if parent is None:
            return None
        try:
            return await parent.fetch_message(channel.id)
        except (discord.Forbidden, discord.HTTPException):
            return None


async def setup(bot: EradicateurBot) -> None:
    await bot.add_cog(ActivityCog(bot))
