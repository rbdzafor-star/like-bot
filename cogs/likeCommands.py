import discord
from discord.ext
import commands, tasks
import json, os, aiohttp
from datetime 
import datetime

CONFIG_FILE = "like_channels.json"
API_URL = os.getenv("API_URL")

class AutoLike(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.config = self.load_config()
        self.auto_like_loop.start()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        return {"servers": {}}

    def save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=4)

    @commands.hybrid_group(name="autolike", description="Manage auto-like list")
    async def autolike(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `/autolike add` or `/autolike remove`")

    @autolike.command(name="add")
    async def autolike_add(self, ctx, uid: str, server: str):
        gid = str(ctx.guild.id)
        conf = self.config["servers"].setdefault(gid, {"like_channels":[],"auto_like":[]})
        for entry in conf["auto_like"]:
            if entry["uid"] == uid and entry["server"] == server:
                return await ctx.send("Already in auto-like list.")
        conf["auto_like"].append({"uid":uid,"server":server})
        self.save_config()
        await ctx.send(f"✅ UID `{uid}` ({server}) added to auto-like list.")

    @autolike.command(name="remove")
    async def autolike_remove(self, ctx, uid: str):
        gid = str(ctx.guild.id)
        conf = self.config["servers"].get(gid, {})
        if not conf: return await ctx.send("No config for this server.")
        conf["auto_like"] = [e for e in conf.get("auto_like",[]) if e["uid"]!=uid]
        self.save_config()
        await ctx.send(f"❌ UID `{uid}` removed from auto-like list.")

    @tasks.loop(hours=24)
    async def auto_like_loop(self):
        """Run once every 24h and send likes."""
        for gid, conf in self.config.get("servers", {}).items():
            for entry in conf.get("auto_like", []):
                try:
                    url = f"{API_URL}/like?uid={entry['uid']}&server={entry['server']}"
                    async with self.session.get(url) as r:
                        print(f"[AUTO] {gid} -> UID {entry['uid']} {r.status}")
                except Exception as e:
                    print(f"AutoLike error: {e}")

    def cog_unload(self):
        self.auto_like_loop.cancel()
        self.bot.loop.create_task(self.session.close())

async def setup(bot):
    await bot.add_cog(AutoLike(bot))
