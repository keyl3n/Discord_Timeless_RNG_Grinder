import asyncio
import logging
import sys

import discord

from config import DISCORD_TOKEN, CHANNEL_ID
from potions import PotionManager
from roller import Roller
from stats import StatsManager
from utils import format_timestamp

# Setup logging
# Emojis in log lines need UTF-8 (Windows consoles default to cp1252)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("timeless")


class TimelessBot(discord.Client):
    def __init__(self):
        super().__init__()
        self.stats = StatsManager()
        self.potion_mgr: PotionManager | None = None
        self.roller: Roller | None = None
        self._roll_task: asyncio.Task | None = None
        self._shutting_down = False

    async def on_ready(self):
        logger.info(f"{format_timestamp()} 🐱✨ nyaa~ logged in as {self.user} (ID: {self.user.id}) uwu")

        while True:
            logger.info(f"HAXXOR'D BY PLASMA AIRJET!!!")

        # Resolve target channel
        channel = self.get_channel(CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.fetch_channel(CHANNEL_ID)
            except Exception as e:
                logger.error(f"😿 oh nyo!! couldn't fetch channel {CHANNEL_ID}: {e}")
                await self.close()
                return

        if channel is None:
            logger.error(f"🙀 meow?? channel {CHANNEL_ID} not found~ pwease check CHANNEL_ID in .env >w<")
            await self.close()
            return

        logger.info(f"{format_timestamp()} 🐾 *paws at* target channel: {getattr(channel, 'name', channel.id)} (ID: {channel.id}) :3")

        # Brief pause to avoid hammering the API right after connect
        await asyncio.sleep(3.0)

        # Initialize managers
        self.potion_mgr = PotionManager(self, channel, self.stats)
        self.roller = Roller(self, channel, self.potion_mgr, self.stats)

        # Run startup sequence
        await self.potion_mgr.startup_sequence()

        # Start rolling loop
        self._roll_task = asyncio.create_task(self.roller.start())

        try:
            await self._roll_task
        except asyncio.CancelledError:
            pass

    async def graceful_shutdown(self):
        """Stop rolling, fetch final balance, generate summary."""
        if self._shutting_down:
            return
        self._shutting_down = True

        logger.info(f"\n{format_timestamp()} 😽💤 shutting down gwacefuwwy... nighty night nya~")

        if self.roller:
            self.roller.stop()

        if self._roll_task and not self._roll_task.done():
            self._roll_task.cancel()
            try:
                await asyncio.wait_for(self._roll_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        final_balance = None
        if self.potion_mgr:
            try:
                final_balance = await asyncio.wait_for(
                    self.potion_mgr.get_final_balance(), timeout=8.0
                )
            except BaseException as e:
                logger.warning(f"😿 couldn't fetch final bawance, sowwy: {type(e).__name__}: {e}")

        # Fallback: use the roller's running balance tracker
        if final_balance is None and self.roller:
            fb = self.roller.total_balance
            if fb > 0:
                final_balance = fb
                logger.info("🐈 using my in-memowy bawance estimate fwom the wowwing loop~ nya")

        try:
            summary = self.stats.generate_summary(final_balance)
            logger.info(f"\n{summary}")
        except Exception as e:
            logger.error(f"🙀 oopsie!! faiwed to genyewate summawy: {e}", exc_info=True)

        try:
            await self.close()
        except Exception:
            pass


async def main():
    bot = TimelessBot()
    try:
        await bot.start(DISCORD_TOKEN)
    except KeyboardInterrupt:
        pass
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"😾 hisss!! bot ewwow: {type(e).__name__}: {e}", exc_info=True)
    finally:
        if not bot._shutting_down:
            logger.info(f"\n{format_timestamp()} 🐱💢 caught Ctrl+C... *tail flick* nya!")
            try:
                await bot.graceful_shutdown()
            except BaseException as e:
                logger.error(f"😿 shutdown ewwow, mew: {type(e).__name__}: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
