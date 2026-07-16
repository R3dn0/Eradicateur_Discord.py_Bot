import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EradicateurBot


class ConfigCog(commands.GroupCog, group_name=app_commands.locale_str("config", key="config_name")):  # type: ignore[call-arg]
    nonotification = app_commands.Group(
        name=app_commands.locale_str("nonotification", key="config_nonotification_name"),
        description=app_commands.locale_str(
            "Manage notification opt-out settings",
            key="config_nonotification_description",
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
    async def opt_out_role(
        self,
        interaction: discord.Interaction,
        role: discord.Role | None = None,
    ) -> None:
        assert self.bot.bot_config_repo is not None
        await self.bot.bot_config_repo.update_opt_out_role(
            role_id=role.id if role else None,
            updated_by=interaction.user.id,
        )

        if role:
            msg = f"Notification opt-out role set to {role.mention}."
        else:
            msg = "Notification opt-out role cleared."
        await interaction.response.send_message(msg, ephemeral=True)

    @nonotification.command(
        name=app_commands.locale_str("show", key="config_nonotification_show_name"),
        description=app_commands.locale_str(
            "Display current notification opt-out configuration",
            key="config_nonotification_show_description",
        ),
    )
    async def show(self, interaction: discord.Interaction) -> None:
        assert self.bot.bot_config_repo is not None
        config = await self.bot.bot_config_repo.get_config()

        guild = interaction.guild
        role = (
            guild.get_role(config.notification_opt_out_role_id)
            if config.notification_opt_out_role_id and guild
            else None
        )
        role_str = role.mention if role else "*Not configured*"

        embed = discord.Embed(
            title="Notification Configuration",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Opt-out role", value=role_str, inline=False)
        if config.updated_by:
            embed.set_footer(text=f"Last updated by <@{config.updated_by}> on {config.updated_at}")
        else:
            embed.set_footer(text=f"Last updated: {config.updated_at}")

        await interaction.response.send_message(embed=embed, ephemeral=True)
