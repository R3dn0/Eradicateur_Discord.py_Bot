import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EradicateurBot

_CATEGORIES: list[tuple[str, list[tuple[str, str, str | None]]]] = [
    (
        "help_category_general",
        [
            ("/ping", "ping_description", None),
        ],
    ),
    (
        "help_category_payout",
        [
            ("/payout creer", "payout_create_description", "help_perm_officer"),
            ("/payout annuler", "payout_void_description", "help_perm_officer"),
            ("/payout config roles", "payout_config_roles_description", "help_perm_administrator"),
            ("/payout config taux", "payout_config_rates_description", "help_perm_leader"),
            (
                "/payout config permissions",
                "payout_config_permissions_description",
                "help_perm_leader",
            ),
            ("/payout config afficher", "payout_config_show_description", None),
            ("/solde payer", "balance_payer_description", "help_perm_pay_add"),
            ("/solde ajouter", "balance_ajouter_description", "help_perm_pay_add"),
        ],
    ),
    (
        "help_category_balance",
        [
            ("/solde afficher", "balance_show_description", None),
            ("/solde historique", "balance_history_description", None),
            ("/solde liste", "balance_list_description", "help_perm_pay_add"),
        ],
    ),
    (
        "help_category_config",
        [
            (
                "/config nonotification role",
                "config_nonotification_role_description",
                "help_perm_administrator",
            ),
            ("/config nonotification afficher", "config_nonotification_show_description", None),
            ("/config logs salon", "config_logs_channel_description", "help_perm_administrator"),
            ("/config logs afficher", "config_logs_show_description", None),
        ],
    ),
]


class HelpCog(commands.Cog):
    def __init__(self, bot: EradicateurBot) -> None:
        self.bot = bot

    @app_commands.command(
        name=app_commands.locale_str("aide", key="help_name"),
        description=app_commands.locale_str(
            "Show the list of available commands", key="help_description"
        ),
    )
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title=await self.bot.translate("help_title", interaction.locale),
            color=discord.Color.blurple(),
        )

        for category_key, entries in _CATEGORIES:
            category_name = await self.bot.translate(category_key, interaction.locale)
            lines: list[str] = []
            for path, desc_key, perm_key in entries:
                desc = await self.bot.translate(desc_key, interaction.locale)
                if perm_key:
                    perm = await self.bot.translate(perm_key, interaction.locale)
                    lines.append(f"`{path}` — {desc} *({perm})*")
                else:
                    lines.append(f"`{path}` — {desc}")
            embed.add_field(name=category_name, value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: EradicateurBot) -> None:
    await bot.add_cog(HelpCog(bot))
