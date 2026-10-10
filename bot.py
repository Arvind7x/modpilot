"""ModPilot — Discord mod-helper bot. Free tier: /faq /ticket /raid work with
zero API. /summarize uses Claude Haiku ONLY if ANTHROPIC_API_KEY is set."""
import asyncio
import json as _json
import os
import threading
import urllib.request as _urlreq

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from flask import Flask

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", "0") or 0)
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OR_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")


def openrouter_chat(system, user, model):
    """One OpenRouter chat call (OpenAI-compatible). No extra dependency."""
    body = _json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 300,
    }).encode()
    req = _urlreq.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://leabert.my.id",
            "X-Title": "ModPilot",
        },
    )
    with _urlreq.urlopen(req, timeout=40) as r:
        out = _json.loads(r.read().decode())
    return out["choices"][0]["message"]["content"]

import json
with open("faqs.json", encoding="utf-8") as f:
    FAQS = json.load(f)

intents = discord.Intents.default()
intents.message_content = True  # enable "Message Content Intent" in the dev portal too

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    try:
        if TEST_GUILD_ID:  # instant command sync while testing (global sync takes ~1h)
            guild = discord.Object(id=TEST_GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        else:
            await bot.tree.sync()
        print(f"Logged in as {bot.user} — commands synced.")
    except Exception as e:
        print("Sync warning:", e)


@bot.tree.command(name="faq", description="Answer a common community question")
@app_commands.describe(topic="Which topic? (bridge, faucet, wallet, rules)")
async def faq(inter: discord.Interaction, topic: str):
    answer = FAQS.get(topic.lower())
    if answer:
        await inter.response.send_message(f"**{topic}**\n{answer}")
    else:
        await inter.response.send_message(
            f"No saved answer for `{topic}`. Topics: {', '.join(FAQS)} — or ask a mod.",
            ephemeral=True,
        )


@bot.tree.command(name="ticket", description="Open a support ticket thread")
@app_commands.describe(problem="Briefly describe your problem")
async def ticket(inter: discord.Interaction, problem: str):
    await inter.response.send_message(
        f"🎫 Ticket opened by {inter.user.mention}: **{problem}**\nA mod will reply here — please add screenshots / wallet / tx hash if relevant."
    )
    try:
        msg = await inter.original_response()
        await msg.create_thread(name=f"ticket-{inter.user.name}", auto_archive_duration=1440)
    except Exception as e:
        await inter.followup.send(f"(Could not create thread: {e})", ephemeral=True)


@bot.tree.command(name="raid", description="Post a raid card")
@app_commands.describe(target="Link or handle to raid", note="Any extra note (optional)")
async def raid(inter: discord.Interaction, target: str, note: str = ""):
    card = f"⚔️ **RAID TIME**\n🎯 Target: {target}\n🕒 Now — be fast, be kind, no spam.\n{('📝 ' + note) if note else ''}"
    await inter.response.send_message(card)


@bot.tree.command(name="summarize", description="AI summary of this thread")
async def summarize(inter: discord.Interaction):
    await inter.response.defer()
    try:
        msgs = []
        async for m in inter.channel.history(limit=20, oldest_first=True):
            if not m.author.bot:
                msgs.append(f"{m.author.display_name}: {m.content[:300]}")
        convo = "\n".join(msgs) or "(empty thread)"
    except Exception as e:
        await inter.followup.send(f"Could not read this thread ({type(e).__name__}).")
        return
    system = "You help crypto-Discord mods. Reply in exactly 3 short lines: 1) user's problem, 2) likely cause/fix, 3) suggested mod reply. Plain text, no fluff."
    # 1) Claude first (keeps the future startup story), 2) OpenRouter fallback
    if ANTHROPIC_KEY:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=ANTHROPIC_KEY)
            resp = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=300,
                system=system,
                messages=[{"role": "user", "content": convo[-4000:]}],
            )
            await inter.followup.send("🧠 **Thread summary** (via Claude)\n" + resp.content[0].text[:1500])
            return
        except Exception as e:
            if not OPENROUTER_KEY:
                await inter.followup.send(f"Claude call failed ({type(e).__name__}). Check key/credits; bot commands still work.")
                return
    if OPENROUTER_KEY:
        try:
            text = await asyncio.to_thread(openrouter_chat, system, convo[-4000:], OR_MODEL)
            await inter.followup.send("🧠 **Thread summary** (via OpenRouter)\n" + (text or "(empty reply)")[:1500]
                                      + f"\n\n_model: {OR_MODEL}_")
            return
        except Exception as e:
            await inter.followup.send(f"AI call failed ({type(e).__name__}: {e}). Check key/credits/model; bot commands still work.")
            return
    await inter.followup.send("AI is offline on this bot (no API key yet) — a mod will reply manually. ✅ Bot itself works fine.")


# ---- keepalive web endpoint (Render free tier + UptimeRobot ping it) ----
app = Flask(__name__)

@app.get("/ping")
def ping():
    return "ok", 200


def run_web():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN — copy .env.example to .env and paste your token.")
    threading.Thread(target=run_web, daemon=True).start()
    bot.run(DISCORD_TOKEN)
