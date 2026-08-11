import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.activity.render import is_activity_embed, parse_embed, render_embed
from bot.cogs.activity.views import (
    ActivityCreateModal,
    PoolConfirmView,
    PoolReorderView,
    build_labels,
    build_view,
)
from bot.main import EradicateurBot
from bot.repositories.activity_pool_repository import ActivityPoolRepository
from bot.utils.discord_guards import require_guild_member


class ActivityCog(
    commands.GroupCog, group_name=app_commands.locale_str("activity", key="activity_name")
):  # type: ignore[call-arg]
    def __init__(self, bot: EradicateurBot) -> None:
        self.bot = bot

    async def _labels(self, interaction: discord.Interaction) -> dict[str, str]:
        return await build_labels(self.bot, interaction.locale)

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

    async def _pool(self, interaction: discord.Interaction) -> ActivityPoolRepository:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        return ActivityPoolRepository(db)

    pool = app_commands.Group(
        name=app_commands.locale_str("pool", key="activity_pool_name"),
        description=app_commands.locale_str(
            "Manage the activity role pool", key="activity_pool_description"
        ),
    )

    @pool.command(
        name=app_commands.locale_str("show", key="activity_pool_show_name"),
        description=app_commands.locale_str(
            "Show the role pool", key="activity_pool_show_description"
        ),
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def pool_show(self, interaction: discord.Interaction) -> None:
        repo = await self._pool(interaction)
        pool_labels = await repo.get_labels(interaction.guild.id)
        embed = discord.Embed(
            title=await self.bot.translate("activity_pool_list_title", interaction.locale),
            color=0xF1C40F,
        )
        if not pool_labels:
            embed.description = await self.bot.translate(
                "activity_pool_empty", interaction.locale
            )
        else:
            embed.description = "\n".join(
                f"{i}. {label}" for i, label in enumerate(pool_labels, start=1)
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @pool.command(
        name=app_commands.locale_str("add", key="activity_pool_add_name"),
        description=app_commands.locale_str(
            "Add a role label to the pool", key="activity_pool_add_description"
        ),
    )
    @app_commands.describe(
        label=app_commands.locale_str(
            "Label shown in the slot (e.g. 🛡️ Tank incub)",
            key="activity_pool_add_label_description",
        ),
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def pool_add(self, interaction: discord.Interaction, label: str) -> None:
        label = label.strip()
        if not label:
            await interaction.response.send_message(
                await self.bot.translate("activity_pool_invalid_label", interaction.locale),
                ephemeral=True,
            )
            return
        repo = await self._pool(interaction)
        await repo.add_label(interaction.guild.id, label[:100])
        text = await self.bot.translate("activity_pool_added", interaction.locale)
        await interaction.response.send_message(
            text.replace("{label}", label[:100]), ephemeral=True
        )

    @pool.command(
        name=app_commands.locale_str("remove", key="activity_pool_remove_name"),
        description=app_commands.locale_str(
            "Remove a role from the pool by position", key="activity_pool_remove_description"
        ),
    )
    @app_commands.describe(
        position=app_commands.locale_str(
            "Position shown by /activity pool show", key="activity_pool_remove_position_description"
        ),
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def pool_remove(self, interaction: discord.Interaction, position: int) -> None:
        if position < 1:
            await interaction.response.send_message(
                await self.bot.translate("activity_pool_invalid_position", interaction.locale),
                ephemeral=True,
            )
            return
        repo = await self._pool(interaction)
        pool_labels = await repo.get_labels(interaction.guild.id)
        if position > len(pool_labels):
            await interaction.response.send_message(
                await self.bot.translate("activity_pool_invalid_position", interaction.locale),
                ephemeral=True,
            )
            return
        label = pool_labels[position - 1]
        view = PoolConfirmView(
            await self.bot.translate("activity_pool_confirm", interaction.locale),
            await self.bot.translate("activity_pool_cancel", interaction.locale),
            on_confirm=lambda inter: self._pool_do_remove(inter, position),
        )
        text = await self.bot.translate("activity_pool_remove_confirm", interaction.locale)
        await interaction.response.send_message(
            text.replace("{position}", str(position)).replace("{label}", label),
            view=view,
            ephemeral=True,
        )

    async def _pool_do_remove(
        self, interaction: discord.Interaction, position: int
    ) -> None:
        repo = await self._pool(interaction)
        removed = await repo.remove_position(interaction.guild.id, position)
        if not removed:
            text = await self.bot.translate(
                "activity_pool_invalid_position", interaction.locale
            )
        else:
            text = await self.bot.translate("activity_pool_removed", interaction.locale)
            text = text.replace("{position}", str(position))
        await interaction.response.edit_message(content=text, view=None)

    @pool.command(
        name=app_commands.locale_str("clear", key="activity_pool_clear_name"),
        description=app_commands.locale_str(
            "Clear the whole pool", key="activity_pool_clear_description"
        ),
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def pool_clear(self, interaction: discord.Interaction) -> None:
        view = PoolConfirmView(
            await self.bot.translate("activity_pool_confirm", interaction.locale),
            await self.bot.translate("activity_pool_cancel", interaction.locale),
            on_confirm=self._pool_do_clear,
        )
        text = await self.bot.translate("activity_pool_clear_confirm", interaction.locale)
        await interaction.response.send_message(text, view=view, ephemeral=True)

    async def _pool_do_clear(self, interaction: discord.Interaction) -> None:
        repo = await self._pool(interaction)
        await repo.clear(interaction.guild.id)
        text = await self.bot.translate("activity_pool_cleared", interaction.locale)
        await interaction.response.edit_message(content=text, view=None)

    @pool.command(
        name=app_commands.locale_str("reorder", key="activity_pool_reorder_name"),
        description=app_commands.locale_str(
            "Reorder the role pool", key="activity_pool_reorder_description"
        ),
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def pool_reorder(self, interaction: discord.Interaction) -> None:
        repo = await self._pool(interaction)
        pool_labels = await repo.get_labels(interaction.guild.id)
        if len(pool_labels) < 2:
            await interaction.response.send_message(
                await self.bot.translate("activity_pool_reorder_need_more", interaction.locale),
                ephemeral=True,
            )
            return
        labels = await self._labels(interaction)
        view = PoolReorderView(labels, self.bot, interaction.locale, pool_labels)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

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
        previous = None
        previous_slot = None
        for i, current_slot in enumerate(activity.slots, start=1):
            if uid in current_slot.players:
                previous = i
                previous_slot = current_slot
                break
        if previous is not None:
            if previous == slot:
                text = await self.bot.translate("activity_already_registered", interaction.locale)
                name = previous_slot.category
                if previous_slot.description:
                    name = f"{name} - {previous_slot.description}"
                await interaction.response.send_message(
                    text.replace("{slot}", name), ephemeral=True
                )
                return
            activity.slots[previous - 1].players.remove(uid)

        activity.slots[slot - 1].players.append(uid)
        labels = await self._labels(interaction)
        embed = render_embed(activity, labels)
        view = build_view(activity, labels, self.bot, interaction.locale, interaction)
        await message.edit(embed=embed, view=view)
        target = activity.slots[slot - 1]
        name = target.category
        if target.description:
            name = f"{name} - {target.description}"
        if previous is not None:
            text = await self.bot.translate("activity_moved", interaction.locale)
        else:
            text = await self.bot.translate("activity_joined", interaction.locale)
        await interaction.response.send_message(text.replace("{slot}", name), ephemeral=True)

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
        slot_obj = None
        for current_slot in activity.slots:
            if uid in current_slot.players:
                current_slot.players.remove(uid)
                slot_obj = current_slot
                break
        if slot_obj is None:
            await interaction.response.send_message(
                await self.bot.translate("activity_not_registered", interaction.locale),
                ephemeral=True,
            )
            return

        labels = await self._labels(interaction)
        embed = render_embed(activity, labels)
        view = build_view(activity, labels, self.bot, interaction.locale, interaction)
        await message.edit(embed=embed, view=view)
        name = slot_obj.category
        if slot_obj.description:
            name = f"{name} - {slot_obj.description}"
        text = await self.bot.translate("activity_left", interaction.locale)
        await interaction.response.send_message(
            text.replace("{slot}", name), ephemeral=True
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
