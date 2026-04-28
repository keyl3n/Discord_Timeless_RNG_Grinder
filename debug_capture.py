"""
debug_capture.py - Captures raw Discord messages, embeds, and components from the Timeless RNG bot.

Run this FIRST before the main bot to understand the actual message structure:
  python debug_capture.py

Then manually type /roll, /buffs, /inventory, /shop etc. in the target channel.
This will log everything so we can verify our parsers are correct.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime

import discord
from dotenv import load_dotenv
import os

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
BOT_ID = int(os.getenv("BOT_ID", "0"))

logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("debug")


def dump_message(msg: discord.Message, label: str = "MESSAGE"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'='*60}")
    print(f"[{ts}] {label}")
    print(f"  Author: {msg.author} (ID: {msg.author.id})")
    print(f"  Channel: {msg.channel.id}")
    print(f"  Content: {repr(msg.content)}")

    if msg.embeds:
        for i, embed in enumerate(msg.embeds):
            print(f"  Embed[{i}]:")
            if embed.title:
                print(f"    title: {repr(embed.title)}")
            if embed.description:
                print(f"    description: {repr(embed.description)}")
            for field in embed.fields:
                print(f"    field '{field.name}': {repr(field.value)}")
            if embed.footer and embed.footer.text:
                print(f"    footer: {repr(embed.footer.text)}")

    if msg.components:
        print(f"  Components:")
        for ri, row in enumerate(msg.components):
            for ci, child in enumerate(row.children):
                if isinstance(child, discord.Button):
                    print(f"    Row[{ri}] Button[{ci}]: label={repr(child.label)} "
                          f"custom_id={repr(getattr(child, 'custom_id', None))} "
                          f"style={child.style} disabled={child.disabled}")
                elif isinstance(child, discord.SelectMenu):
                    print(f"    Row[{ri}] SelectMenu[{ci}]: custom_id={repr(getattr(child, 'custom_id', None))}")
                    for opt in child.options:
                        print(f"      Option: label={repr(opt.label)} value={repr(opt.value)} "
                              f"description={repr(opt.description)}")
                else:
                    print(f"    Row[{ri}] Component[{ci}]: type={type(child).__name__} {vars(child)}")

    # Also save raw data to file
    try:
        raw = {
            "timestamp": datetime.now().isoformat(),
            "label": label,
            "author_id": msg.author.id,
            "author_name": str(msg.author),
            "content": msg.content,
            "embeds": [
                {
                    "title": e.title,
                    "description": e.description,
                    "fields": [{"name": f.name, "value": f.value} for f in e.fields],
                    "footer": e.footer.text if e.footer else None,
                }
                for e in msg.embeds
            ],
            "components": [
                {
                    "type": type(child).__name__,
                    "label": getattr(child, "label", None),
                    "custom_id": getattr(child, "custom_id", None),
                    "options": [
                        {"label": o.label, "value": o.value, "description": o.description}
                        for o in getattr(child, "options", [])
                    ],
                }
                for row in msg.components
                for child in row.children
            ],
        }
        with open("debug_captures.json", "a") as f:
            f.write(json.dumps(raw) + "\n")
    except Exception as e:
        print(f"  [Could not save to debug_captures.json: {e}]")


class DebugClient(discord.Client):
    async def on_ready(self):
        print(f"\n{'='*60}")
        print(f"Debug bot ready as: {self.user} (ID: {self.user.id})")
        print(f"Watching channel ID: {CHANNEL_ID}")
        print(f"Filtering bot ID: {BOT_ID}")
        print(f"Manually send commands in that channel (/roll, /buffs, /inventory, /shop).")
        print(f"All messages from bot ID {BOT_ID} will be captured and logged here.")
        print(f"Also saving to debug_captures.json")
        print(f"Press Ctrl+C to stop.")
        print(f"{'='*60}\n")

        # Also try listing available application commands
        try:
            channel = self.get_channel(CHANNEL_ID) or await self.fetch_channel(CHANNEL_ID)
            print(f"Fetching available application commands in channel...")
            cmds = await channel.application_commands()
            timeless_cmds = [c for c in cmds if c.application_id == BOT_ID]
            print(f"  Timeless RNG commands ({len(timeless_cmds)}):")
            for cmd in timeless_cmds:
                print(f"    /{cmd.name} (id={cmd.id}, app_id={cmd.application_id})")
            if not timeless_cmds:
                print(f"  None found for bot ID {BOT_ID}")
                print(f"  All commands ({len(cmds)}):")
                for cmd in cmds[:20]:
                    print(f"    /{cmd.name} (app_id={cmd.application_id})")
        except Exception as e:
            print(f"  Could not fetch application commands: {e}")

    async def on_message(self, message: discord.Message):
        if message.channel.id != CHANNEL_ID:
            return
        if message.author.id == BOT_ID:
            dump_message(message, "BOT MESSAGE")

    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.channel.id != CHANNEL_ID:
            return
        if after.author.id == BOT_ID:
            dump_message(after, "BOT MESSAGE EDIT")


async def main():
    client = DebugClient()
    try:
        await client.start(DISCORD_TOKEN)
    except KeyboardInterrupt:
        await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
