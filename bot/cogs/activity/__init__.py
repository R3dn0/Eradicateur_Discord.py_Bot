from bot.cogs.activity.cog import ActivityCog


async def setup(bot):
    await bot.add_cog(ActivityCog(bot))
