import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EradicateurBot
from bot.repositories.bot_config_repository import BotConfigRepository
from bot.utils.discord_guards import require_guild_member
from bot.utils.discord_time import to_discord_timestamp


class ConfigCog(commands.GroupCog, group_name=app_commands.locale_str("config", key="config_name")):  # type: ignore[call-arg]
    nonotification = app_commands.Group(
        name=app_commands.locale_str("nonotification", key="config_nonotification_name"),
        description=app_commands.locale_str(
            "Manage notification opt-out settings",
            key="config_nonotification_description",
        ),
    )

    logs = app_commands.Group(
        name=app_commands.locale_str("logs", key="config_logs_name"),
        description=app_commands.locale_str(
            "Manage audit log channel",
            key="config_logs_description",
        ),
    )

    def __init__(self, bot: EradicateurBot) -> None:
        self.bot = bot

    @nonotification.command(
        name=app_commands.locale_str("role", key="config_nonotification_role_name"),
        description=app_commands.locale_str(
            "Set or clear the role whose members opt out of payout DMs",
            key="config_nonotification_role_description",
        ),
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        role=app_commands.locale_str(
            "Role to opt out of DMs. Omit to clear.",
            key="config_nonotification_role_param_description",
        ),
    )
    @require_guild_member
    async def opt_out_role(
        self,
        interaction: discord.Interaction,
        role: discord.Role | None = None,
    ) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        bot_config_repo = BotConfigRepository(db)

        await bot_config_repo.update_opt_out_role(
            role_id=role.id if role else None,
            updated_by=interaction.user.id,
        )

        if role:
            template = await self.bot.translate(
                "config_nonotification_role_set", interaction.locale
            )
            msg = template.replace("{role}", role.mention)
        else:
            msg = await self.bot.translate("config_nonotification_role_cleared", interaction.locale)
        await interaction.response.send_message(msg, ephemeral=True)

    @nonotification.command(
        name=app_commands.locale_str("show", key="config_nonotification_show_name"),
        description=app_commands.locale_str(
            "Display current notification opt-out configuration",
            key="config_nonotification_show_description",
        ),
    )
    @require_guild_member
    async def show(self, interaction: discord.Interaction) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        bot_config_repo = BotConfigRepository(db)
        config = await bot_config_repo.get_config()

        guild = interaction.guild
        role = (
            guild.get_role(config.notification_opt_out_role_id)
            if config.notification_opt_out_role_id and guild
            else None
        )
        not_configured = await self.bot.translate("payout_not_configured", interaction.locale)
        role_str = role.mention if role else not_configured

        embed = discord.Embed(
            title=await self.bot.translate(
                "config_nonotification_show_embed_title", interaction.locale
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(
            name=await self.bot.translate(
                "config_nonotification_show_opt_out_role", interaction.locale
            ),
            value=role_str,
            inline=False,
        )
        if config.updated_by:
            value = (
                (
                    await self.bot.translate(
                        "config_nonotification_show_updated_by", interaction.locale
                    )
                )
                .replace("{user}", f"<@{config.updated_by}>")
                .replace("{date}", to_discord_timestamp(config.updated_at))
            )
        else:
            value = (
                await self.bot.translate("config_nonotification_show_updated", interaction.locale)
            ).replace("{date}", to_discord_timestamp(config.updated_at))
        embed.add_field(
            name=await self.bot.translate(
                "config_nonotification_show_updated_label", interaction.locale
            ),
            value=value,
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @logs.command(
        name=app_commands.locale_str("channel", key="config_logs_channel_name"),
        description=app_commands.locale_str(
            "Set or clear the audit log channel for command usage",
            key="config_logs_channel_description",
        ),
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        salon=app_commands.locale_str(
            "Channel to log command usage. Omit to clear.",
            key="config_logs_channel_param_description",
        ),
    )
    @require_guild_member
    async def log_channel(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel | None = None,
    ) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        bot_config_repo = BotConfigRepository(db)

        await bot_config_repo.update_log_channel(
            channel_id=salon.id if salon else None,
            updated_by=interaction.user.id,
        )

        if salon:
            template = await self.bot.translate("config_logs_channel_set", interaction.locale)
            msg = template.replace("{channel}", salon.mention)
        else:
            msg = await self.bot.translate("config_logs_channel_cleared", interaction.locale)
        await interaction.response.send_message(msg, ephemeral=True)

    @logs.command(
        name=app_commands.locale_str("show", key="config_logs_show_name"),
        description=app_commands.locale_str(
            "Display current audit log channel configuration",
            key="config_logs_show_description",
        ),
    )
    @require_guild_member
    async def log_show(self, interaction: discord.Interaction) -> None:
        assert self.bot.db_manager is not None
        db = await self.bot.db_manager.get_connection(interaction.guild.id)
        bot_config_repo = BotConfigRepository(db)
        config = await bot_config_repo.get_config()

        guild = interaction.guild
        channel = (
            guild.get_channel(config.log_channel_id) if config.log_channel_id and guild else None
        )
        not_configured = await self.bot.translate("payout_not_configured", interaction.locale)
        channel_str = channel.mention if channel else not_configured

        embed = discord.Embed(
            title=await self.bot.translate("config_logs_show_embed_title", interaction.locale),
            color=discord.Color.blue(),
        )
        embed.add_field(
            name=await self.bot.translate("config_logs_show_channel", interaction.locale),
            value=channel_str,
            inline=False,
        )
        if config.updated_by:
            value = (
                (
                    await self.bot.translate(
                        "config_nonotification_show_updated_by", interaction.locale
                    )
                )
                .replace("{user}", f"<@{config.updated_by}>")
                .replace("{date}", to_discord_timestamp(config.updated_at))
            )
        else:
            value = (
                await self.bot.translate("config_nonotification_show_updated", interaction.locale)
            ).replace("{date}", to_discord_timestamp(config.updated_at))
        embed.add_field(
            name=await self.bot.translate("config_logs_show_updated_label", interaction.locale),
            value=value,
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
