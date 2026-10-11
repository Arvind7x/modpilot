"""ModPilot — Discord mod-helper bot. Free tier: /faq /ticket /raid work with
zero API. /summarize uses Claude Haiku ONLY if ANTHROPIC_API_KEY is set."""
import asyncio
import json as _json
import os
import re
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
        "max_tokens": 400,
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

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]+"
)


def clean_ai(text):
    """Strip emojis + collapse blank lines. Seatbelt for the no-emoji rule."""
    return re.sub(r"\n{3,}", "\n\n", EMOJI_RE.sub("", text or "")).strip()


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


@bot.tree.error
async def on_app_error(inter: discord.Interaction, error: app_commands.AppCommandError):
    """Never die silent — always answer the user with something readable."""
    try:
        msg = "Glitched for a sec — try the command again. If it keeps failing, tell a mod."
        if inter.response.is_done():
            await inter.followup.send(msg, ephemeral=True)
        else:
            await inter.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


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


@bot.tree.command(name="ticket", description="Open a private support ticket")
@app_commands.describe(problem="Briefly describe your problem")
async def ticket(inter: discord.Interaction, problem: str):
    # Fast public ack with NO private details, so the interaction never times out.
    await inter.response.send_message("🎫 Opening your private ticket…")
    stub = await inter.original_response()
    thread = None
    for dur in (1440, 60):  # 24h needs boosts on some servers; 60 works everywhere
        try:
            thread = await stub.create_thread(
                name=f"ticket-{inter.user.name}"[:90],
                auto_archive_duration=dur,
                type=discord.ChannelType.private_thread,
            )
            break
        except Exception:
            thread = None
    if thread is None:
        await inter.followup.send(
            "Couldn't open a private ticket here — this server needs the **Create Private Threads** "
            "permission re-authorised. Ask an admin to re-open my invite link, then try again.",
            ephemeral=True,
        )
        return
    try:
        await thread.add_user(inter.user)
        await thread.send(
            f"**Ticket from {inter.user.mention}**\nProblem: **{problem}**\n"
            "Mods: please reply here. User: add screenshots / wallet / tx hash if relevant."
        )
        await stub.edit(content="🎫 Ticket opened — mods, check your private threads.")
        await inter.followup.send(
            f"Your private ticket is ready: {thread.jump_url} — only you and the mods can see it.",
            ephemeral=True,
        )
    except Exception as e:
        await inter.followup.send(
            f"Ticket thread is open but setup hiccuped ({type(e).__name__}) — mods can still see it.",
            ephemeral=True,
        )


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
        async for m in inter.channel.history(limit=40, oldest_first=True):
            if not m.author.bot:
                msgs.append(f"{m.author.display_name}: {m.content[:300]}")
        convo = "\n".join(msgs) or "(empty thread)"
    except Exception as e:
        await inter.followup.send(f"Could not read this thread ({type(e).__name__}).")
        return
    system = (
        "Summarize this Discord thread for a busy moderator. Plain facts only: "
        "no greetings, no jokes, no vibe commentary, zero emojis, under 60 words. "
        "Format exactly like this:\n"
        "Problem: <one line>\n"
        "Fix: <one line>\n"
        "Reply: <one line the mod can paste>"
    )
    # 1) Claude first (keeps the future startup story), 2) OpenRouter fallback
    if ANTHROPIC_KEY:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=ANTHROPIC_KEY)
            resp = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=400,
                system=system,
                messages=[{"role": "user", "content": convo[-6000:]}],
            )
            await inter.followup.send((clean_ai(resp.content[0].text) or "(empty reply)")[:1500])
            return
        except Exception as e:
            if not OPENROUTER_KEY:
                await inter.followup.send(f"Claude call failed ({type(e).__name__}). Check key/credits; bot commands still work.")
                return
    if OPENROUTER_KEY:
        try:
            text = await asyncio.to_thread(openrouter_chat, system, convo[-6000:], OR_MODEL)
            text = clean_ai(text) or "(empty reply)"
            await inter.followup.send(text[:1500])
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


async def boot_with_retry():
    """Login with backoff. Render's shared IP sometimes gets temp-banned by
    Discord (Cloudflare 429) for other people's abuse — ride it out instead
    of crash-looping. Bad tokens still fail fast and loud."""
    wait = 60
    attempt = 0
    while True:
        attempt += 1
        try:
            print(f"Login attempt {attempt}…", flush=True)
            await bot.start(DISCORD_TOKEN)
            return  # clean shutdown only
        except discord.errors.LoginFailure:
            print("DISCORD_TOKEN is invalid — fix the token, not retrying.", flush=True)
            raise
        except discord.errors.HTTPException as e:
            if getattr(e, "status", None) == 429:
                wait = min(wait, 600)
                print(f"Rate-limited at login (shared-IP ban?) — retrying in {wait}s…", flush=True)
                await asyncio.sleep(wait)
                wait *= 2
                continue
            raise


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN — copy .env.example to .env and paste your token.")
    threading.Thread(target=run_web, daemon=True).start()
    asyncio.run(boot_with_retry())
