from bot.cogs.activity.cog import ActivityCog
from bot.cogs.activity.views import make_persistent_view


async def setup(bot):
    await bot.add_cog(ActivityCog(bot))
    bot.add_view(make_persistent_view(bot))
