import asyncio
import logging

import discord

from config import (
    BOT_ID, TARGET_BUFFS, PURCHASE_PRIORITY, POTIONS,
    RELEVANT_POTIONS,
)
from shop import ShopInteraction, send_slash_command
from stats import StatsManager
from utils import (
    get_embed_text,
    parse_buffs, parse_inventory, parse_balance,
    parse_useitem_response, format_timestamp,
)

logger = logging.getLogger("timeless")


class PotionManager:
    """Manages buff detection, potion inventory, purchasing, and consumption."""

    def __init__(self, client: discord.Client, channel, stats: StatsManager):
        self.client = client
        self.channel = channel
        self.stats = stats
        self.shop = ShopInteraction(client, channel)
        self.active_buffs: dict[str, str] = {}  # {name: remaining_info}
        self.inventory: dict[str, int] = {}  # {name: count}
        self.balance: int = 0
        self.replenishment_enabled: bool = True
        self.last_known_luck: float | None = None

    async def send_command(self, command_name: str, **options) -> discord.Message | None:
        """Send a slash command and wait for bot response."""
        return await send_slash_command(
            self.client, self.channel, BOT_ID, command_name, **options
        )

    async def check_buffs(self) -> dict[str, str]:
        """Send /buffs and parse active buffs."""
        msg = await self.send_command("buffs")
        if msg is None:
            logger.warning("😿 couldn't fetch buffs, mew...")
            return {}

        text = get_embed_text(msg)
        self.active_buffs = parse_buffs(text)
        logger.info(f"🧪✨ active buffs: {self.active_buffs} nya~")
        return self.active_buffs

    async def check_inventory(self) -> tuple[dict[str, int], int]:
        """Send /inventory and parse items + balance."""
        msg = await self.send_command("inventory")
        if msg is None:
            logger.warning("😿 couldn't fetch inventowy, mew...")
            return {}, 0

        text = get_embed_text(msg)
        items, balance = parse_inventory(text)

        # Filter to relevant potions only
        self.inventory = {k: v for k, v in items.items() if k in RELEVANT_POTIONS}
        self.balance = balance
        logger.info(f"🎒 inventowy: {self.inventory} | 💰 bawance: ${self.balance:,} nya~")
        return self.inventory, self.balance

    async def startup_sequence(self) -> bool:
        """Execute the full startup sequence. Returns True if ready to roll."""
        logger.info(f"{format_timestamp()} 🐱🔍 stawting up - checking buffs and inventowy... *sniff sniff*")

        # Step 1: Check current buffs
        await self.check_buffs()
        await asyncio.sleep(3.0)

        # Step 2: Check inventory and balance
        await self.check_inventory()
        await asyncio.sleep(3.0)

        # Register initial balance
        self.stats.set_initial_balance(self.balance)

        buff_list = list(self.active_buffs.keys()) if self.active_buffs else ["None"]
        inv_list = [f"{k}x{v}" for k, v in self.inventory.items()] if self.inventory else ["None"]
        logger.info(
            f"{format_timestamp()} ✅🐾 bot initiawized uwu | 💰 Bawance: ${self.balance:,} "
            f"| 🧪 Active buffs: {', '.join(buff_list)} | 🎒 Inventowy potions: {', '.join(inv_list)}"
        )

        # Step 3: Calculate what we need
        needs = self._calculate_needs()
        if not needs:
            logger.info("😸✨ aww tawget buffs awe awweady active! weady to woww nya~!")
            return True

        # Step 4: Use inventory potions first
        await self._consume_inventory_potions(needs)

        # Step 5: Purchase remaining needs
        if needs:
            await self._execute_purchases(needs)

        return True

    def _calculate_needs(self) -> dict[str, int]:
        """Calculate what potions need to be purchased/used.

        /buffs only shows one entry per buff type regardless of how many are stacked,
        so we can't count stacks — just check presence. If a buff is active at all,
        skip it. If it's absent, buy+use the full target count.
        """
        needs = {}
        for potion_name, target_count in TARGET_BUFFS.items():
            is_active = any(
                potion_name.lower() in buff_name.lower()
                for buff_name in self.active_buffs
            )
            if not is_active:
                needs[potion_name] = target_count
        return needs

    async def _consume_inventory_potions(self, needs: dict[str, int]):
        """Use potions from inventory to meet needs. Modifies needs dict in-place."""
        for potion_name in list(needs.keys()):
            available = self.inventory.get(potion_name, 0)
            if available > 0:
                use_count = min(available, needs[potion_name])
                success = await self._use_item(potion_name, use_count)
                if success:
                    needs[potion_name] -= use_count
                    if needs[potion_name] <= 0:
                        del needs[potion_name]
                    self.inventory[potion_name] = available - use_count
                await asyncio.sleep(2.0)

    async def _use_item(self, item_name: str, amount: int) -> bool:
        """Send /useitem command and confirm activation."""
        logger.info(f"🧪 using {amount}x {item_name} fwom inventowy... *paws at bottwe*")
        # discord.py-self passes slash command options as keyword args
        msg = await self.send_command("useitem", item=item_name, amount=str(amount))
        if msg is None:
            logger.error(f"🙀 faiwed to use {item_name} - no wesponse, nyooo")
            return False

        text = get_embed_text(msg)
        success, expires = parse_useitem_response(text)
        if success:
            expires_str = f" Expires in: {expires}" if expires else ""
            logger.info(f"  ✅😻 used {amount}x {item_name}.{expires_str} yay nya~")
        else:
            logger.warning(f"  😵‍💫 uncleaw /useitem wesponse fow {item_name}: {text[:150]} (mew??)")
        return success

    async def _execute_purchases(self, needs: dict[str, int]):
        """Buy potions based on priority and available balance."""
        if self.balance == 0:
            # Inventory might have failed to parse balance — try fetching from shop
            logger.info("🪙😿 bawance weads $0 fwom inventowy; vewifying via /shop... *squints*")
            shop_balance = await self.shop.get_balance_from_shop()
            if shop_balance:
                self.balance = shop_balance
                logger.info(f"💰😸 bawance confiwmed fwom shop: ${self.balance:,} nya~")
            else:
                logger.warning(f"{format_timestamp()} ⚠️😿 bawance is $0. cannyot puwchase potions, sowwy mew...")
                if not self.inventory:
                    logger.warning("🙀 nyo inventowy potions avaiwabwe. wowwing without buffs~ >w<")
                    self.replenishment_enabled = False
                return

        # Calculate total cost of all needs
        total_needed_cost = sum(
            needs.get(name, 0) * POTIONS[name]["cost"]
            for name in needs
        )

        if self.balance < 1_350:
            logger.warning(
                f"{format_timestamp()} ⚠️😿 bawance ${self.balance:,} < $1,350. "
                "cannyot affowd any potion. wowwing without buffs to buiwd capitaw~ nya"
            )
            # Don't permanently disable — re-check next periodic buff check
            return

        # Open shop
        shop_msg = await self.shop.open_shop()
        if shop_msg is None:
            logger.error("😿 couldn't open shop. pwoceeding without puwchases, mew...")
            return

        buy_plan = []
        remaining_balance = self.balance

        # Build purchase plan based on priority
        for potion_name in PURCHASE_PRIORITY:
            qty_needed = needs.get(potion_name, 0)
            if qty_needed <= 0:
                continue

            cost_each = POTIONS[potion_name]["cost"]
            affordable_qty = min(qty_needed, remaining_balance // cost_each)

            if affordable_qty > 0:
                buy_plan.append((potion_name, affordable_qty))
                remaining_balance -= affordable_qty * cost_each

        if not buy_plan:
            logger.warning("😿 cannyot affowd any needed potions, sowwy nya...")
            return

        plan_str = ", ".join(f"{qty}x {name}" for name, qty in buy_plan)
        total_cost = self.balance - remaining_balance
        logger.info(
            f"{format_timestamp()} 📊🐾 puwchasing pwan | 🛒 Buying: {plan_str} "
            f"| 💸 Cost: ${total_cost:,} | 🪙 Wemaining bawance: ${remaining_balance:,} nya~"
        )

        # Execute purchases by shop page; track what was actually bought
        actually_bought: dict[str, int] = {}  # {name: qty_actually_purchased}
        current_page = 1
        for potion_name, qty in buy_plan:
            target_page = POTIONS[potion_name].get("shop_page", 1)

            # Re-open shop only when switching to a new item on page 1,
            # or when we need to start fresh. For page 2+ items, we navigate
            # from where we already are (don't reset to page 1 by re-opening).
            if target_page == 1 or current_page == 1:
                if await self.shop.open_shop() is None:
                    logger.error("🙀 couldn't we-open shop, stopping puwchases... nyooo")
                    break
                current_page = 1
                self.shop._log_page_contents("page 1 after open")

            if target_page != current_page:
                logger.info(f"📖🐾 nyavigating to page {target_page} fow {potion_name}...")
                if await self.shop.navigate_to_page(target_page):
                    current_page = target_page
                    logger.info(f"📖😸 nyow on page {target_page}, items: {self.shop._get_current_page_items()} uwu")
                else:
                    logger.error(f"🙀 faiwed to nyavigate to page {target_page}, skipping {potion_name}... mew")
                    continue

            success, spent = await self.shop.buy_item(potion_name, qty)
            if spent > 0:
                self.stats.record_purchase(spent)
                self.balance -= spent
                cost_each = POTIONS[potion_name]["cost"]
                actual_qty = spent // cost_each
                if actual_qty > 0:
                    actually_bought[potion_name] = actual_qty
            await asyncio.sleep(2.0)

        # Only use what was actually purchased (not the planned qty)
        await asyncio.sleep(5.0)  # let rate limits settle after shop activity
        for potion_name, actual_qty in actually_bought.items():
            await self._use_item(potion_name, actual_qty)
            await asyncio.sleep(2.0)

    async def check_and_replenish(self, current_luck: float | None):
        """Check if buffs expired and replenish if needed."""
        if not self.replenishment_enabled:
            return

        if current_luck is None or self.last_known_luck is None:
            self.last_known_luck = current_luck
            return

        prev_luck = self.last_known_luck
        luck_dropped = prev_luck - current_luck if current_luck < prev_luck else 0
        self.last_known_luck = current_luck

        if luck_dropped < 0.2:
            return

        # Luck dropped significantly - a buff likely expired
        logger.info(
            f"{format_timestamp()} ⚠️🍀😿 wuck dwopped: {prev_luck} → {current_luck}. "
            "checking buffs fow wepwenishment... *ears flatten*"
        )

        await self.check_buffs()
        # If check_buffs returned empty (timeout/429), retry once before acting.
        # An empty result when we know luck was high = parse failure, not genuinely no buffs.
        if not self.active_buffs and prev_luck > 1.0:
            logger.info("🧪🙀 buff check wetuwned empty — twying once mowe befowe puwchasing... mew?")
            await asyncio.sleep(3.0)
            await self.check_buffs()
            if not self.active_buffs:
                logger.warning("🧪😾 buff check stiww empty aftew wetwy — skipping wepwenishment to avoid ovew-buying~ nya")
                return

        needs = self._calculate_needs()

        if needs:
            logger.info(f"🧪🐱 wepwenishment needed: {needs} nya~")
            # Wait for rolling rate-limits to settle before hammering the shop
            logger.info("⏳😽 waiting 8s fow wate wimits to settwe befowe shop... *curls up*")
            await asyncio.sleep(8.0)
            # Check balance before replenishing
            await self.check_inventory()
            await self._consume_inventory_potions(needs)
            if needs:
                await self._execute_purchases(needs)

    async def get_final_balance(self) -> int | None:
        """Fetch final balance via /shop for shutdown summary."""
        balance = await self.shop.get_balance_from_shop()
        if balance is not None:
            return balance
        # Fallback: check inventory
        await self.check_inventory()
        return self.balance if self.balance > 0 else None
