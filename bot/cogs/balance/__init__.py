from bot.cogs.balance.cog import BalanceCog


async def setup(bot):
    await bot.add_cog(BalanceCog(bot))
