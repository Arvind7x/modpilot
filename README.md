# ModPilot 🤖

A Discord mod-helper bot built for crypto communities. Live 24/7.

**Commands:** `/faq` instant answers · `/ticket` private support threads · `/raid` raid cards · `/summarize` AI thread summaries

**Demo:** https://x.com/0xBiosnm/status/2109155989849276630

## Run it yourself (free)

1. Discord Developer Portal → New Application → copy bot token, enable **Message Content Intent** + **Server Members Intent**
2. Invite URL: OAuth2 → tick `bot` + `applications.commands` → Send Messages, Create Public/Private Threads, Send Messages in Threads, Read Message History
3. `cp .env.example .env` → paste `DISCORD_TOKEN` (+ optional `TEST_GUILD_ID`, `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY`)
4. `pip install -r requirements.txt` → `python bot.py`

No API keys? Everything except `/summarize` works. AI providers are optional fallbacks: Claude first, OpenRouter second.

## Deploy free

Render Web Service (free tier): build `pip install -r requirements.txt`, start `python bot.py`, set the same env vars in the dashboard. Add an UptimeRobot monitor on `/ping` to keep it warm.

## Tech

Python · discord.py · Flask keepalive · Claude Haiku / OpenRouter

## License

MIT — see [LICENSE](LICENSE).
