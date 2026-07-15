import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EradicateurBot


class PayoutCreateModal(discord.ui.Modal):
    bag_silvers: discord.ui.TextInput
    item_market_value: discord.ui.TextInput
    activity_cost: discord.ui.TextInput

    def __init__(
        self,
        title: str,
        bag_label: str,
        bag_placeholder: str,
        item_label: str,
        item_placeholder: str,
        cost_label: str,
        cost_placeholder: str,
        invalid_msg: str,
    ) -> None:
        super().__init__(timeout=300, title=title)
        self._invalid_msg = invalid_msg
        self.bag_silvers = discord.ui.TextInput(
            label=bag_label,
            placeholder=bag_placeholder,
            required=True,
        )
        self.add_item(self.bag_silvers)
        self.item_market_value = discord.ui.TextInput(
            label=item_label,
            placeholder=item_placeholder,
            required=True,
        )
        self.add_item(self.item_market_value)
        self.activity_cost = discord.ui.TextInput(
            label=cost_label,
            placeholder=cost_placeholder,
            required=True,
        )
        self.add_item(self.activity_cost)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            bag_silvers = float(self.bag_silvers.value)
            item_market_value = float(self.item_market_value.value)
            activity_cost = float(self.activity_cost.value)
        except ValueError:
            await interaction.response.send_message(
                self._invalid_msg,
                ephemeral=True,
            )
            return

        bot: EradicateurBot = interaction.client  # type: ignore
        select_msg = await bot.translate("payout_select_participants", interaction.locale)
        select_placeholder = await bot.translate("payout_select_placeholder", interaction.locale)
        finish_label = await bot.translate("payout_finish", interaction.locale)
        cancel_label = await bot.translate("payout_cancel", interaction.locale)
        retirer_label = await bot.translate("payout_retirer", interaction.locale)
        retour_label = await bot.translate("payout_retour", interaction.locale)
        remove_prompt = await bot.translate("payout_remove_prompt", interaction.locale)
        remove_placeholder = await bot.translate("payout_remove_placeholder", interaction.locale)
        view = ParticipantSelectView(
            bag_silvers,
            item_market_value,
            activity_cost,
            select_placeholder,
            finish_label,
            cancel_label,
            retirer_label,
            retour_label,
            remove_prompt,
            remove_placeholder,
        )
        await interaction.response.send_message(
            select_msg,
            view=view,
            ephemeral=True,
        )


class ParticipantSelectView(discord.ui.View):
    def __init__(
        self,
        bag_silvers: float,
        item_market_value: float,
        activity_cost: float,
        select_placeholder: str,
        finish_label: str,
        cancel_label: str,
        retirer_label: str,
        retour_label: str,
        remove_prompt: str,
        remove_placeholder: str,
    ) -> None:
        super().__init__(timeout=300)
        self.bag_silvers = bag_silvers
        self.item_market_value = item_market_value
        self.activity_cost = activity_cost
        self.accumulated: set[int] = set()
        self._retour_label = retour_label
        self._remove_prompt = remove_prompt
        self._remove_placeholder = remove_placeholder
        self._terminer_button: discord.ui.Button | None = None
        self._retirer_button: discord.ui.Button | None = None
        for child in self.children:
            if isinstance(child, discord.ui.UserSelect):
                child.placeholder = select_placeholder
            elif isinstance(child, discord.ui.Button):
                if child.label == "terminer":
                    child.label = finish_label
                    child.disabled = True
                    self._terminer_button = child
                elif child.label == "retirer":
                    child.label = retirer_label
                    child.disabled = True
                    self._retirer_button = child
                elif child.label == "annuler":
                    child.label = cancel_label

    def _build_recap(self) -> str:
        mentions = " ".join(f"<@{uid}>" for uid in self.accumulated)
        return f"Participants sélectionnés ({len(self.accumulated)}) : {mentions}"

    def _update_button_states(self) -> None:
        non_empty = len(self.accumulated) > 0
        if self._terminer_button is not None:
            self._terminer_button.disabled = not non_empty
        if self._retirer_button is not None:
            self._retirer_button.disabled = not non_empty

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        max_values=25,
    )
    async def on_participants_selected(
        self,
        interaction: discord.Interaction,
        select: discord.ui.UserSelect,
    ) -> None:
        self.accumulated.update(m.id for m in select.values)
        self._update_button_states()
        await interaction.response.edit_message(
            content=self._build_recap(),
            view=self,
        )

    @discord.ui.button(label="terminer", style=discord.ButtonStyle.green)
    async def terminer(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not interaction.guild:
            bot: EradicateurBot = interaction.client  # type: ignore
            msg = await bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        bot: EradicateurBot = interaction.client  # type: ignore
        assert bot.payout_config_service is not None
        rates = await bot.payout_config_service.get_rates()

        n = len(self.accumulated)

        guild_cut = self.bag_silvers * rates.guild
        silver_pool = self.bag_silvers - guild_cut
        silver_per_player = int(silver_pool // n)

        total_taxes = rates.market + rates.guild + rates.transport
        item_net = max(0, (self.item_market_value - self.activity_cost) * (1 - total_taxes))
        item_per_player = int(item_net // n)

        total_per_player = silver_per_player + item_per_player
        total_pool = silver_pool + item_net
        buyback_value = self.item_market_value * (1 - rates.market - rates.transport)

        embed_keys = {
            "title": await bot.translate("payout_embed_title", interaction.locale),
            "gain": await bot.translate("payout_embed_gain", interaction.locale),
            "item": await bot.translate("payout_embed_item", interaction.locale),
            "cost": await bot.translate("payout_embed_cost", interaction.locale),
            "participants": await bot.translate("payout_embed_participants", interaction.locale),
            "split": await bot.translate("payout_embed_split", interaction.locale),
            "amount": await bot.translate("payout_embed_amount", interaction.locale),
            "buyback": await bot.translate("payout_embed_buyback", interaction.locale),
            "list": await bot.translate("payout_embed_list", interaction.locale),
            "confirm": await bot.translate("payout_confirm", interaction.locale),
            "cancel": await bot.translate("payout_cancel", interaction.locale),
        }

        mentions = "\n".join(f"<@{uid}>" for uid in self.accumulated)
        embed = discord.Embed(
            title=embed_keys["title"],
            color=discord.Color.dark_gold(),
        )
        embed.add_field(name=embed_keys["gain"], value=f"{self.bag_silvers:,.0f}", inline=True)
        embed.add_field(
            name=embed_keys["item"], value=f"{self.item_market_value:,.0f}", inline=True
        )
        embed.add_field(name=embed_keys["cost"], value=f"{self.activity_cost:,.0f}", inline=True)
        embed.add_field(
            name=embed_keys["buyback"],
            value=f"{buyback_value:,.0f}",
            inline=True,
        )
        embed.add_field(name=embed_keys["participants"], value=str(n), inline=True)
        embed.add_field(
            name=embed_keys["split"],
            value=f"{total_pool:,.0f}",
            inline=True,
        )
        embed.add_field(
            name=embed_keys["amount"],
            value=f"{total_per_player:,.0f}",
            inline=False,
        )
        embed.add_field(name=embed_keys["list"], value=mentions, inline=False)

        view = ConfirmCancelView(
            bag_silvers=self.bag_silvers,
            item_market_value=self.item_market_value,
            activity_cost=self.activity_cost,
            tax_market=rates.market,
            tax_guild=rates.guild,
            tax_transport=rates.transport,
            amount_per_player=float(total_per_player),
            buyback_value=buyback_value,
            total_pool=total_pool,
            participant_ids=list(self.accumulated),
            participant_mentions=mentions,
            confirm_label=embed_keys["confirm"],
            cancel_label=embed_keys["cancel"],
        )
        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=view,
        )

    @discord.ui.button(label="retirer", style=discord.ButtonStyle.secondary)
    async def retirer(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        view = RemoveParticipantsView(
            accumulated=self.accumulated,
            main_view=self,
            remove_placeholder=self._remove_placeholder,
            retour_label=self._retour_label,
        )
        await interaction.response.edit_message(
            content=self._remove_prompt,
            view=view,
        )

    @discord.ui.button(label="annuler", style=discord.ButtonStyle.red)
    async def annuler(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        bot: EradicateurBot = interaction.client  # type: ignore
        cancelled = await bot.translate("payout_cancelled", interaction.locale)
        for child in self.children:
            child.disabled = True  # type: ignore
        await interaction.response.edit_message(
            content=cancelled,
            embed=None,
            view=self,
        )


class RemoveParticipantsView(discord.ui.View):
    def __init__(
        self,
        accumulated: set[int],
        main_view: ParticipantSelectView,
        remove_placeholder: str,
        retour_label: str,
    ) -> None:
        super().__init__(timeout=300)
        self.accumulated = accumulated
        self._main_view = main_view
        self._retour_label = retour_label
        for child in self.children:
            if isinstance(child, discord.ui.UserSelect):
                child.placeholder = remove_placeholder
            elif isinstance(child, discord.ui.Button) and child.label == "retour":
                child.label = retour_label

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        max_values=25,
    )
    async def on_remove_selected(
        self,
        interaction: discord.Interaction,
        select: discord.ui.UserSelect,
    ) -> None:
        self.accumulated.difference_update(m.id for m in select.values)
        self._main_view._update_button_states()
        await interaction.response.edit_message(
            content=self._main_view._build_recap(),
            view=self._main_view,
        )

    @discord.ui.button(label="retour", style=discord.ButtonStyle.secondary)
    async def retour(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self._main_view._update_button_states()
        await interaction.response.edit_message(
            content=self._main_view._build_recap(),
            view=self._main_view,
        )


class ConfirmCancelView(discord.ui.View):
    def __init__(
        self,
        bag_silvers: float,
        item_market_value: float,
        activity_cost: float,
        tax_market: float,
        tax_guild: float,
        tax_transport: float,
        amount_per_player: float,
        buyback_value: float,
        total_pool: float,
        participant_ids: list[int],
        participant_mentions: str,
        confirm_label: str,
        cancel_label: str,
    ) -> None:
        super().__init__(timeout=300)
        self.bag_silvers = bag_silvers
        self.item_market_value = item_market_value
        self.activity_cost = activity_cost
        self.tax_market = tax_market
        self.tax_guild = tax_guild
        self.tax_transport = tax_transport
        self.amount_per_player = amount_per_player
        self.buyback_value = buyback_value
        self.total_pool = total_pool
        self.participant_ids = participant_ids
        self.participant_mentions = participant_mentions
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
        bot: EradicateurBot = interaction.client  # type: ignore
        assert bot.payout_repo is not None
        assert interaction.channel is not None

        n = len(self.participant_ids)
        created_by = interaction.user.id
        payout_id = await bot.payout_repo.create_payout(
            bag_silvers=self.bag_silvers,
            item_market_value=self.item_market_value,
            activity_cost=self.activity_cost,
            tax_market=self.tax_market,
            tax_guild=self.tax_guild,
            tax_transport=self.tax_transport,
            amount_per_player=self.amount_per_player,
            buyback_value=self.buyback_value,
            participant_ids=self.participant_ids,
            created_by=created_by,
        )

        assert bot.transaction_repo is not None
        assert bot.payout_config_repo is not None
        payout_config = await bot.payout_config_repo.get_config()
        no_dm_role_id = payout_config.no_dm_role_id

        dm_title = await bot.translate("payout_dm_title", interaction.locale)
        dm_received = await bot.translate("payout_dm_received", interaction.locale)
        dm_new_balance = await bot.translate("payout_dm_new_balance", interaction.locale)

        failed_dms: list[int] = []
        skipped_dms: list[int] = []
        for participant_id in self.participant_ids:
            member = interaction.guild.get_member(participant_id) if interaction.guild else None
            if member is None:
                try:
                    if interaction.guild is None:
                        failed_dms.append(participant_id)
                        continue
                    member = await interaction.guild.fetch_member(participant_id)
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    failed_dms.append(participant_id)
                    continue

            if no_dm_role_id is not None and member.get_role(no_dm_role_id):
                skipped_dms.append(participant_id)
                continue

            new_balance = await bot.transaction_repo.get_balance(participant_id)

            dm_embed = discord.Embed(
                title=dm_title,
                color=discord.Color.gold(),
            )
            dm_embed.add_field(
                name=dm_received, value=f"{self.amount_per_player:,.0f}", inline=True
            )
            dm_embed.add_field(name=dm_new_balance, value=f"{new_balance:,.0f}", inline=True)

            try:
                await member.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException):
                failed_dms.append(participant_id)

        item_label = await bot.translate("payout_embed_item", interaction.locale)
        gain_label = await bot.translate("payout_embed_gain", interaction.locale)
        cost_label = await bot.translate("payout_embed_cost", interaction.locale)
        part_label = await bot.translate("payout_embed_participants", interaction.locale)
        split_label = await bot.translate("payout_embed_split", interaction.locale)
        buyback_label = await bot.translate("payout_embed_buyback", interaction.locale)
        amount_label = await bot.translate("payout_embed_amount", interaction.locale)
        list_label = await bot.translate("payout_embed_list", interaction.locale)

        public_embed = discord.Embed(
            title=f"Payout #{payout_id}",
            color=discord.Color.gold(),
        )
        public_embed.add_field(name=item_label, value=f"{self.item_market_value:,.0f}", inline=True)
        public_embed.add_field(name=gain_label, value=f"{self.bag_silvers:,.0f}", inline=True)
        public_embed.add_field(name=cost_label, value=f"{self.activity_cost:,.0f}", inline=True)
        public_embed.add_field(
            name=buyback_label,
            value=f"{self.buyback_value:,.0f}",
            inline=False,
        )
        public_embed.add_field(name=part_label, value=str(n), inline=True)
        public_embed.add_field(
            name=split_label,
            value=f"{self.total_pool:,.0f}",
            inline=True,
        )
        public_embed.add_field(
            name=amount_label,
            value=f"{self.amount_per_player:,.0f}",
            inline=False,
        )
        public_embed.add_field(name=list_label, value=self.participant_mentions, inline=False)

        await interaction.channel.send(embed=public_embed)  # type: ignore

        success = await bot.translate("payout_success", interaction.locale)
        success = success.replace("{id}", str(payout_id)).replace("{n}", str(n))

        if skipped_dms:
            optout_note = await bot.translate("payout_dm_optout_note", interaction.locale)
            success += "\n" + optout_note.replace("{n}", str(len(skipped_dms)))

        if failed_dms:
            failure_note = await bot.translate("payout_dm_failure_note", interaction.locale)
            failed_mentions = ", ".join(f"<@{uid}>" for uid in failed_dms)
            success += "\n" + failure_note.replace("{users}", failed_mentions)

        for child in self.children:
            child.disabled = True  # type: ignore
        await interaction.response.edit_message(
            content=success,
            embed=None,
            view=self,
        )

    @discord.ui.button(label="cancel", style=discord.ButtonStyle.red)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        bot: EradicateurBot = interaction.client  # type: ignore
        cancelled = await bot.translate("payout_cancelled", interaction.locale)

        for child in self.children:
            child.disabled = True  # type: ignore
        await interaction.response.edit_message(
            content=cancelled,
            embed=None,
            view=self,
        )


class PayoutCog(commands.GroupCog, group_name=app_commands.locale_str("payout", key="payout_name")):  # type: ignore[call-arg]
    config = app_commands.Group(
        name=app_commands.locale_str("config", key="payout_config_name"),
        description=app_commands.locale_str(
            "Configure payout settings", key="payout_config_description"
        ),
    )

    def __init__(self, bot: EradicateurBot) -> None:
        self.bot = bot

    @app_commands.command(
        name=app_commands.locale_str("create", key="payout_create_name"),
        description=app_commands.locale_str(
            "Create a new payout from a guild activity",
            key="payout_create_description",
        ),
    )
    async def create(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            msg = await self.bot.translate("payout_server_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        assert self.bot.payout_config_service is not None
        if not await self.bot.payout_config_service.is_officer(interaction.user):
            msg = await self.bot.translate("payout_officer_only", interaction.locale)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        title = await self.bot.translate("payout_modal_title", interaction.locale)
        bag_label = await self.bot.translate("payout_modal_bag_label", interaction.locale)
        bag_placeholder = await self.bot.translate(
            "payout_modal_bag_placeholder", interaction.locale
        )
        item_label = await self.bot.translate("payout_modal_item_label", interaction.locale)
        item_placeholder = await self.bot.translate(
            "payout_modal_item_placeholder", interaction.locale
        )
        cost_label = await self.bot.translate("payout_modal_cost_label", interaction.locale)
        cost_placeholder = await self.bot.translate(
            "payout_modal_cost_placeholder", interaction.locale
        )
        invalid_msg = await self.bot.translate("payout_modal_invalid_number", interaction.locale)

        modal = PayoutCreateModal(
            title=title,
            bag_label=bag_label,
            bag_placeholder=bag_placeholder,
            item_label=item_label,
            item_placeholder=item_placeholder,
            cost_label=cost_label,
            cost_placeholder=cost_placeholder,
            invalid_msg=invalid_msg,
        )
        await interaction.response.send_modal(modal)

    @config.command(
        name=app_commands.locale_str("roles", key="payout_config_roles_name"),
        description=app_commands.locale_str(
            "Set the officer and leader roles for payout management",
            key="payout_config_roles_description",
        ),
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        officer="Officer role",
        leader="Leader role",
        no_dm=app_commands.locale_str(
            "Role whose members opt out of payout DMs",
            key="payout_config_roles_no_dm_description",
        ),
    )
    async def config_roles(
        self,
        interaction: discord.Interaction,
        officer: discord.Role,
        leader: discord.Role,
        no_dm: discord.Role | None = None,
    ) -> None:
        assert self.bot.payout_config_repo is not None

        config = await self.bot.payout_config_repo.get_config()
        no_dm_role_id = config.no_dm_role_id if no_dm is None else no_dm.id

        await self.bot.payout_config_repo.update_roles(
            officer_role_id=officer.id,
            leader_role_id=leader.id,
            no_dm_role_id=no_dm_role_id,
        )

        msg = f"Roles configured: officer = {officer.mention}, " f"leader = {leader.mention}"
        if no_dm:
            msg += f", no-DM = {no_dm.mention}"
        await interaction.response.send_message(msg, ephemeral=True)

    @config.command(
        name=app_commands.locale_str("rates", key="payout_config_rates_name"),
        description=app_commands.locale_str(
            "Update the tax rates used in payout calculations",
            key="payout_config_rates_description",
        ),
    )
    async def config_rates(
        self,
        interaction: discord.Interaction,
        market: float,
        guild: float,
        transport: float,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        assert self.bot.payout_config_service is not None
        assert self.bot.payout_config_repo is not None
        if not await self.bot.payout_config_service.is_leader(interaction.user):
            await interaction.response.send_message(
                "You need the leader role to change tax rates.", ephemeral=True
            )
            return

        await self.bot.payout_config_repo.update_rates(
            market=market, guild=guild, transport=transport
        )

        def _fmt(v: float) -> str:
            return f"{v:.2%}".rstrip("0").rstrip(".")

        await interaction.response.send_message(
            f"Rates updated: market = {_fmt(market)}, guild = {_fmt(guild)}, transport = {_fmt(transport)}",
            ephemeral=True,
        )

    @config.command(
        name=app_commands.locale_str("show", key="payout_config_show_name"),
        description=app_commands.locale_str(
            "Display current payout configuration",
            key="payout_config_show_description",
        ),
    )
    async def config_show(self, interaction: discord.Interaction) -> None:
        assert self.bot.payout_config_repo is not None
        config = await self.bot.payout_config_repo.get_config()

        guild = interaction.guild
        officer_role = (
            guild.get_role(config.officer_role_id) if config.officer_role_id and guild else None
        )
        officer = officer_role.mention if officer_role else "*Not configured*"
        leader_role = (
            guild.get_role(config.leader_role_id) if config.leader_role_id and guild else None
        )
        leader = leader_role.mention if leader_role else "*Not configured*"
        no_dm_role = (
            guild.get_role(config.no_dm_role_id) if config.no_dm_role_id and guild else None
        )
        no_dm = no_dm_role.mention if no_dm_role else "*Not configured*"

        embed = discord.Embed(
            title="Payout Configuration",
            color=discord.Color.blue(),
        )

        def _fmt(v: float) -> str:
            return f"{v:.2%}".rstrip("0").rstrip(".")

        embed.add_field(name="Market tax", value=f"{_fmt(config.tax_market)}", inline=True)
        embed.add_field(name="Guild tax", value=f"{_fmt(config.tax_guild)}", inline=True)
        embed.add_field(name="Transport tax", value=f"{_fmt(config.tax_transport)}", inline=True)
        embed.add_field(name="Officer role", value=officer, inline=False)
        embed.add_field(name="Leader role", value=leader, inline=False)
        embed.add_field(name="No-DM role", value=no_dm, inline=False)
        embed.set_footer(text=f"Last updated: {config.updated_at}")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: EradicateurBot) -> None:
    await bot.add_cog(PayoutCog(bot))
