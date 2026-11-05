import asyncio
import logging

import discord

from config import BOT_ID, ROLL_DELAY, COOLDOWN_RETRY_DELAY, ROLL_FAILURE_BACKOFF, BUFF_CHECK_INTERVAL
from potions import PotionManager
from shop import send_slash_command
from stats import StatsManager
from utils import (
    get_embed_text,
    parse_auras, parse_roll_number, parse_coins_earned,
    parse_luck_value, compact_aura_str, format_timestamp,
)

logger = logging.getLogger("timeless")


class Roller:
    """Main rolling loop: sends /roll, parses responses, manages buffs."""

    def __init__(self, client: discord.Client, channel, potion_mgr: PotionManager, stats: StatsManager):
        self.client = client
        self.channel = channel
        self.potion_mgr = potion_mgr
        self.stats = stats
        self._running = False
        self.total_balance: int = 0

    async def start(self):
        """Start the rolling loop."""
        self._running = True
        self.total_balance = self.potion_mgr.balance
        self._roll_count = 0
        self._last_roll_num: int | None = None
        logger.info(f"{format_timestamp()} 🎲🐾 starting wowwing loop... wet's go nya~!")

        while self._running:
            try:
                t0 = asyncio.get_event_loop().time()
                success = await self._do_roll()
                elapsed = asyncio.get_event_loop().time() - t0

                if success:
                    self._roll_count += 1
                    if self._roll_count % BUFF_CHECK_INTERVAL == 0:
                        await self._periodic_buff_check()
                    # Only sleep the remaining time needed to hit ROLL_DELAY.
                    # If retries/latency already ate into it, don't add extra delay.
                    remaining = ROLL_DELAY - elapsed
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                else:
                    # Roll failed — short back-off before retrying
                    await asyncio.sleep(ROLL_FAILURE_BACKOFF)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"😿 oh nyo, ewwow during woww: {e}", exc_info=True)
                await asyncio.sleep(2.0)

    async def _periodic_buff_check(self):
        """Called every BUFF_CHECK_INTERVAL rolls to proactively replenish buffs."""
        await self.potion_mgr.check_buffs()
        # Retry if empty — could be a parse failure, not genuinely no buffs
        if not self.potion_mgr.active_buffs:
            await asyncio.sleep(3.0)
            await self.potion_mgr.check_buffs()
        needs = self.potion_mgr._calculate_needs()
        if needs:
            logger.info(f"{format_timestamp()} 🔄🧪 pewiodic buff check~ *sniff sniff* wepwenishing {needs} nya")
            await self.potion_mgr.check_inventory()
            await self.potion_mgr._consume_inventory_potions(needs)
            if needs:
                await self.potion_mgr._execute_purchases(needs)

    def stop(self):
        self._running = False

    async def _do_roll(self) -> bool:
        """Send a single /roll and process the response. Returns True on success."""
        msg = await send_slash_command(self.client, self.channel, BOT_ID, "roll")

        # No response (transient miss) — retry once immediately before giving up
        if msg is None:
            if not self._running:
                return False
            logger.debug("🙀 no wesponse fwom /woww — twying once mowe~ mew")
            await asyncio.sleep(1.0)
            msg = await send_slash_command(self.client, self.channel, BOT_ID, "roll")
            if msg is None:
                logger.warning("😿 stiww no wesponse fwom /woww aftew wetwy... sadge nya")
                return False

        text = get_embed_text(msg)

        # Handle cooldown — wait just enough then try again
        if "cooldown" in text.lower():
            logger.debug("⏳😾 cooldown hit, hisss~ waiting and wetwying... *tail swish*")
            await asyncio.sleep(COOLDOWN_RETRY_DELAY)
            msg = await send_slash_command(self.client, self.channel, BOT_ID, "roll")
            if msg is None:
                return False
            text = get_embed_text(msg)

        auras = parse_auras(text)
        roll_num = parse_roll_number(text)
        coins = parse_coins_earned(text) or 0
        luck = parse_luck_value(text)

        # Skip duplicate roll (same number seen twice due to 429 retry)
        if roll_num is not None and roll_num == self._last_roll_num:
            return True
        self._last_roll_num = roll_num

        self.total_balance += coins
        self.stats.record_roll(roll_num, auras, coins, luck)

        roll_str = f"#{roll_num:,}" if roll_num else "?"
        luck_str = str(luck) if luck is not None else "?"
        logger.info(
            f"{format_timestamp()} 🎲 Woww {roll_str} | ✨ Auwas: {compact_aura_str(auras)} "
            f"| 💰 Coins: +${coins:,} (Totaw: ${self.total_balance:,}) | 🍀 Luck: {luck_str} nya~ 🐱"
        )

        await self.potion_mgr.check_and_replenish(luck)
        return True
