import logging
from datetime import datetime, timezone

import discord

from bot.main import EradicateurBot
from bot.repositories.bot_config_repository import BotConfigRepository
from bot.repositories.payout_config_repository import (
    PayoutConfigRepository,
)
from bot.repositories.payout_repository import PayoutRepository
from bot.repositories.transaction_repository import (
    TransactionRepository,
)
from bot.services.payout_config_service import PayoutConfigService
from bot.services.payout_service import PayoutSplitResult, compute_split
from bot.utils.discord_dm import send_bulk_dm
from bot.utils.discord_time import to_discord_timestamp

logger = logging.getLogger("eradicateur_bot.payout")


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
            bag_silvers = int(self.bag_silvers.value)
            item_market_value = int(self.item_market_value.value)
            activity_cost = int(self.activity_cost.value)
        except ValueError:
            await interaction.response.send_message(self._invalid_msg, ephemeral=True)
            return

        if bag_silvers <= 0 or item_market_value <= 0 or activity_cost < 0:
            await interaction.response.send_message(self._invalid_msg, ephemeral=True)
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
        bag_silvers: int,
        item_market_value: int,
        activity_cost: int,
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
        bots_skipped = 0
        for member in select.values:
            if member.bot:
                bots_skipped += 1
            else:
                self.accumulated.add(member.id)
        self._update_button_states()
        content = self._build_recap()
        if bots_skipped:
            bot: EradicateurBot = interaction.client  # type: ignore
            note = await bot.translate("payout_bot_skipped", interaction.locale)
            content += f"\n{note}"
        await interaction.response.edit_message(
            content=content,
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
        assert bot.db_manager is not None
        db = await bot.db_manager.get_connection(interaction.guild.id)
        payout_config_repo = PayoutConfigRepository(db)
        payout_config_service = PayoutConfigService(payout_config_repo)
        rates = await payout_config_service.get_rates()

        n = len(self.accumulated)
        split = compute_split(
            bag_silvers=self.bag_silvers,
            item_market_value=self.item_market_value,
            activity_cost=self.activity_cost,
            rates=rates,
            participant_count=n,
        )

        embed_keys = {
            "title": await bot.translate("payout_embed_title", interaction.locale),
            "gain": await bot.translate("payout_embed_gain", interaction.locale),
            "item": await bot.translate("payout_embed_item", interaction.locale),
            "cost": await bot.translate("payout_embed_cost", interaction.locale),
            "participants": await bot.translate("payout_embed_participants", interaction.locale),
            "split": await bot.translate("payout_embed_split", interaction.locale),
            "buyback": await bot.translate("payout_embed_buyback", interaction.locale),
            "per_player": await bot.translate("payout_embed_per_player", interaction.locale),
            "created_by": await bot.translate("payout_embed_created_by", interaction.locale),
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
            name=embed_keys["split"],
            value=f"{split.total_pool:,.0f}",
            inline=True,
        )
        embed.add_field(
            name=embed_keys["buyback"],
            value=f"{split.buyback_value:,.0f}",
            inline=True,
        )
        participants_value = f"{mentions}\n{embed_keys['per_player'].replace('{amount}', f'{split.amount_per_player:,.0f}')}"
        embed.add_field(
            name=f"{embed_keys['participants']}",
            value=participants_value,
            inline=False,
        )
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        dev_users = getattr(getattr(bot, "config", None), "dashboard_dev_users", None) or [135489084385787905]
        is_dev = interaction.user.id in dev_users
        user_mention = "Dev 😎" if is_dev else interaction.user.mention
        created_value = (
            embed_keys["created_by"]
            .replace("{user}", user_mention)
            .replace("{date}", to_discord_timestamp(now_str))
        )
        embed.add_field(name="\u200b", value=created_value, inline=False)

        view = ConfirmCancelView(
            bag_silvers=self.bag_silvers,
            item_market_value=self.item_market_value,
            activity_cost=self.activity_cost,
            tax_market=rates.market,
            tax_guild=rates.guild,
            tax_transport=rates.transport,
            split=split,
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
        bag_silvers: int,
        item_market_value: int,
        activity_cost: int,
        tax_market: float,
        tax_guild: float,
        tax_transport: float,
        split: PayoutSplitResult,
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
        self.split = split
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
        await interaction.response.defer(ephemeral=True)
        bot: EradicateurBot = interaction.client  # type: ignore
        assert interaction.channel is not None
        assert interaction.guild is not None
        assert bot.db_manager is not None
        db = await bot.db_manager.get_connection(interaction.guild.id)

        payout_repo = PayoutRepository(db, TransactionRepository(db))
        bot_config_repo = BotConfigRepository(db)
        payout_config_repo = PayoutConfigRepository(db)
        transaction_repo = TransactionRepository(db)

        n = len(self.participant_ids)
        created_by = interaction.user.id

        try:
            payout_id = await payout_repo.create_payout(
                bag_silvers=self.bag_silvers,
                item_market_value=self.item_market_value,
                activity_cost=self.activity_cost,
                tax_market=self.tax_market,
                tax_guild=self.tax_guild,
                tax_transport=self.tax_transport,
                amount_per_player=self.split.amount_per_player,
                buyback_value=self.split.buyback_value,
                participant_ids=self.participant_ids,
                created_by=created_by,
            )
            logger.info(
                "[Discord] User: %s (ID: %s) | Action: PAYOUT_CREATE | Payout #%s | Total Loot: %s | Participants: %s | Net/Player: %s",
                interaction.user.display_name,
                interaction.user.id,
                payout_id,
                self.bag_silvers + self.item_market_value,
                n,
                self.split.amount_per_player,
            )
        except Exception:
            logger.exception(
                'Failed to create payout — guild=%s "%s" participants=%d',
                interaction.guild.id,
                interaction.guild.name,
                n,
            )
            failed_msg = await bot.translate("payout_create_failed", interaction.locale)
            try:
                await interaction.edit_original_response(
                    content=failed_msg,
                    embed=None,
                    view=self,
                )
            except Exception:
                logger.exception("Failed to send payout creation error response")
            return

        bot_config = await bot_config_repo.get_config()
        no_dm_role_id = bot_config.notification_opt_out_role_id

        dm_title = await bot.translate("payout_dm_title", interaction.locale)
        dm_received = await bot.translate("payout_dm_received", interaction.locale)
        dm_new_balance = await bot.translate("payout_dm_new_balance", interaction.locale)

        async def _build_content(member: discord.Member) -> discord.Embed:
            new_balance = await transaction_repo.get_balance(member.id)
            embed = discord.Embed(
                title=dm_title,
                color=discord.Color.gold(),
            )
            embed.add_field(
                name=dm_received, value=f"{self.split.amount_per_player:,.0f}", inline=True
            )
            embed.add_field(name=dm_new_balance, value=f"{new_balance:,.0f}", inline=True)
            return embed

        context_template = await bot.translate("dm_context", interaction.locale)
        action = f"Payout #{payout_id}"
        context = context_template.replace("{user}", f"<@{interaction.user.id}>").replace(
            "{action}", action
        )
        result = await send_bulk_dm(
            guild=interaction.guild,
            member_ids=self.participant_ids,
            build_content=_build_content,
            opt_out_role_id=no_dm_role_id,
            context=context,
        )

        item_label = await bot.translate("payout_embed_item", interaction.locale)
        gain_label = await bot.translate("payout_embed_gain", interaction.locale)
        cost_label = await bot.translate("payout_embed_cost", interaction.locale)
        part_label = await bot.translate("payout_embed_participants", interaction.locale)
        split_label = await bot.translate("payout_embed_split", interaction.locale)
        buyback_label = await bot.translate("payout_embed_buyback", interaction.locale)
        per_player_label = await bot.translate("payout_embed_per_player", interaction.locale)
        created_by_label = await bot.translate("payout_embed_created_by", interaction.locale)

        public_embed = discord.Embed(
            title=f"Payout #{payout_id}",
            color=discord.Color.gold(),
        )
        public_embed.add_field(name=item_label, value=f"{self.item_market_value:,.0f}", inline=True)
        public_embed.add_field(name=gain_label, value=f"{self.bag_silvers:,.0f}", inline=True)
        public_embed.add_field(name=cost_label, value=f"{self.activity_cost:,.0f}", inline=True)
        public_embed.add_field(
            name=split_label,
            value=f"{self.split.total_pool:,.0f}",
            inline=True,
        )
        public_embed.add_field(
            name=buyback_label,
            value=f"{self.split.buyback_value:,.0f}",
            inline=True,
        )
        participants_value = f"{self.participant_mentions}\n{per_player_label.replace('{amount}', f'{self.split.amount_per_player:,.0f}')}"
        public_embed.add_field(
            name=f"{part_label} ({n})",
            value=participants_value,
            inline=False,
        )
        payout_obj = await payout_repo.get_payout(payout_id)
        dev_users = getattr(getattr(bot, "config", None), "dashboard_dev_users", None) or [135489084385787905]
        is_dev = interaction.user.id in dev_users
        user_mention = "Dev 😎" if is_dev else interaction.user.mention
        created_value = created_by_label.replace("{user}", user_mention).replace(
            "{date}",
            to_discord_timestamp(payout_obj.created_at),  # type: ignore
        )
        public_embed.add_field(name="\u200b", value=created_value, inline=False)

        payout_cfg = await payout_config_repo.get_config()
        target_channel = (
            interaction.guild.get_channel(payout_cfg.payout_channel_id)
            if payout_cfg.payout_channel_id and interaction.guild
            else interaction.channel
        ) or interaction.channel

        announce_failed = False
        try:
            await target_channel.send(embed=public_embed)  # type: ignore
        except Exception:
            logger.exception(
                'Payout %s created but public announcement failed — guild=%s "%s"',
                payout_id,
                interaction.guild.id,
                interaction.guild.name,
            )
            announce_failed = True

        if announce_failed:
            template = await bot.translate("payout_announce_failed", interaction.locale)
            success = template.replace("{id}", str(payout_id))
        else:
            success = await bot.translate("payout_success", interaction.locale)
            success = success.replace("{id}", str(payout_id)).replace("{n}", str(n))

            if result.skipped:
                optout_note = await bot.translate("payout_dm_optout_note", interaction.locale)
                success += "\n" + optout_note.replace("{n}", str(len(result.skipped)))

            if result.failed:
                failure_note = await bot.translate("payout_dm_failure_note", interaction.locale)
                failed_mentions = ", ".join(f"<@{uid}>" for uid in result.failed)
                success += "\n" + failure_note.replace("{users}", failed_mentions)

        for child in self.children:
            child.disabled = True  # type: ignore
        try:
            await interaction.edit_original_response(
                content=success,
                embed=None,
                view=self,
            )
        except Exception:
            logger.exception(
                'Failed to edit original response after payout %s — guild=%s "%s"',
                payout_id,
                interaction.guild.id,
                interaction.guild.name,
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
