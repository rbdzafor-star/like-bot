import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import json
import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
API_URL = os.getenv("API_URL")
CONFIG_FILE = "like_channels.json"


class AutoLike(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_host = API_URL
        self.session = aiohttp.ClientSession()

        # Load existing config or create new
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                self.config_data = json.load(f)
        else:
            self.config_data = {"servers": {}}
            self.save_config()

    def save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config_data, f, indent=4)

    def get_auto_list(self, guild_id: str):
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        return server_config.setdefault("auto_like", [])

    # --- Commands ---

    @commands.hybrid_command(name="autolike", description="Manage auto-like UIDs for this server")
    @app_commands.describe(action="add/remove/list", uid="Player UID", server="Region/server code")
    async def autolike(self, ctx: commands.Context, action: str, uid: str = None, server: str = None):
        guild_id = str(ctx.guild.id)
        auto_like_list = self.get_auto_list(guild_id)

        if action.lower() == "add":
            if not uid or not server:
                return await ctx.send("❌ You must provide both UID and server.")
            entry = {"uid": uid, "server": server}
            if entry in auto_like_list:
                return await ctx.send("⚠️ That UID is already in the auto-like list.")
            auto_like_list.append(entry)
            self.save_config()
            await ctx.send(f"✅ UID **{uid}** from server **{server}** has been added to the auto-like list for this server.")

        elif action.lower() == "remove":
            if not uid:
                return await ctx.send("❌ Provide a UID to remove.")
            before = len(auto_like_list)
            auto_like_list[:] = [e for e in auto_like_list if e["uid"] != uid]
            self.save_config()
            if len(auto_like_list) < before:
                await ctx.send(f"✅ UID **{uid}** removed from the auto-like list.")
            else:
                await ctx.send("⚠️ UID not found in the auto-like list.")

        elif action.lower() == "list":
            if not auto_like_list:
                return await ctx.send("📭 No UIDs in the auto-like list.")
            desc = "\n".join([f"• **{e['uid']}** ({e['server']})" for e in auto_like_list])
            embed = discord.Embed(title="📌 Auto-Like List", description=desc, color=0x2ECC71, timestamp=datetime.now())
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Invalid action. Use `add`, `remove`, or `list`.")

    # --- Background Auto-Like Task ---
    async def cog_load(self):
        self.bot.loop.create_task(self.auto_like_task())

    async def auto_like_task(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            for guild_id, config in self.config_data["servers"].items():
                auto_like_list = config.get("auto_like", [])
                for entry in auto_like_list:
                    uid = entry["uid"]
                    server = entry["server"]
                    try:
                        url = f"{self.api_host}/like?uid={uid}&server={server}"
                        async with self.session.get(url) as response:
                            if response.status == 200:
                                print(f"[AUTO-LIKE] ✅ UID {uid} ({server}) liked successfully")
                            else:
                                print(f"[AUTO-LIKE] ❌ Failed for {uid} ({server}) - {response.status}")
                    except Exception as e:
                        print(f"[AUTO-LIKE] Error for {uid}: {e}")
            await asyncio.sleep(24 * 60 * 60)  # run every 24 hours

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())


async def setup(bot):
    await bot.add_cog(AutoLike(bot))
