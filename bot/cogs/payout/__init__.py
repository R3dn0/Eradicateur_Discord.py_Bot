from bot.cogs.payout.cog import PayoutCog


async def setup(bot):
    await bot.add_cog(PayoutCog(bot))
