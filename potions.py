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
            logger.warning("Could not fetch buffs")
            return {}

        text = get_embed_text(msg)
        self.active_buffs = parse_buffs(text)
        logger.info(f"Active buffs: {self.active_buffs}")
        return self.active_buffs

    async def check_inventory(self) -> tuple[dict[str, int], int]:
        """Send /inventory and parse items + balance."""
        msg = await self.send_command("inventory")
        if msg is None:
            logger.warning("Could not fetch inventory")
            return {}, 0

        text = get_embed_text(msg)
        items, balance = parse_inventory(text)

        # Filter to relevant potions only
        self.inventory = {k: v for k, v in items.items() if k in RELEVANT_POTIONS}
        self.balance = balance
        logger.info(f"Inventory: {self.inventory} | Balance: ${self.balance:,}")
        return self.inventory, self.balance

    async def startup_sequence(self) -> bool:
        """Execute the full startup sequence. Returns True if ready to roll."""
        logger.info(f"{format_timestamp()} Starting up - checking buffs and inventory...")

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
            f"{format_timestamp()} ✅ Bot initialized | Balance: ${self.balance:,} "
            f"| Active buffs: {', '.join(buff_list)} | Inventory potions: {', '.join(inv_list)}"
        )

        # Step 3: Calculate what we need
        needs = self._calculate_needs()
        if not needs:
            logger.info("All target buffs are already active. Ready to roll!")
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
        logger.info(f"Using {amount}x {item_name} from inventory...")
        # discord.py-self passes slash command options as keyword args
        msg = await self.send_command("useitem", item=item_name, amount=str(amount))
        if msg is None:
            logger.error(f"Failed to use {item_name} - no response")
            return False

        text = get_embed_text(msg)
        success, expires = parse_useitem_response(text)
        if success:
            expires_str = f" Expires in: {expires}" if expires else ""
            logger.info(f"  ✅ Used {amount}x {item_name}.{expires_str}")
        else:
            logger.warning(f"  Unclear /useitem response for {item_name}: {text[:150]}")
        return success

    async def _execute_purchases(self, needs: dict[str, int]):
        """Buy potions based on priority and available balance."""
        if self.balance == 0:
            # Inventory might have failed to parse balance — try fetching from shop
            logger.info("Balance reads $0 from inventory; verifying via /shop...")
            shop_balance = await self.shop.get_balance_from_shop()
            if shop_balance:
                self.balance = shop_balance
                logger.info(f"Balance confirmed from shop: ${self.balance:,}")
            else:
                logger.warning(f"{format_timestamp()} ⚠️ Balance is $0. Cannot purchase potions.")
                if not self.inventory:
                    logger.warning("No inventory potions available. Rolling without buffs.")
                    self.replenishment_enabled = False
                return

        # Calculate total cost of all needs
        total_needed_cost = sum(
            needs.get(name, 0) * POTIONS[name]["cost"]
            for name in needs
        )

        if self.balance < 1_350:
            logger.warning(
                f"{format_timestamp()} ⚠️ Balance ${self.balance:,} < $1,350. "
                "Cannot afford any potion. Rolling without buffs to build capital."
            )
            # Don't permanently disable — re-check next periodic buff check
            return

        # Open shop
        shop_msg = await self.shop.open_shop()
        if shop_msg is None:
            logger.error("Could not open shop. Proceeding without purchases.")
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
            logger.warning("Cannot afford any needed potions.")
            return

        plan_str = ", ".join(f"{qty}x {name}" for name, qty in buy_plan)
        total_cost = self.balance - remaining_balance
        logger.info(
            f"{format_timestamp()} 📊 Purchasing plan | Buying: {plan_str} "
            f"| Cost: ${total_cost:,} | Remaining balance: ${remaining_balance:,}"
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
                    logger.error("Could not re-open shop, stopping purchases")
                    break
                current_page = 1
                self.shop._log_page_contents("page 1 after open")

            if target_page != current_page:
                logger.info(f"Navigating to page {target_page} for {potion_name}...")
                if await self.shop.navigate_to_page(target_page):
                    current_page = target_page
                    logger.info(f"Now on page {target_page}, items: {self.shop._get_current_page_items()}")
                else:
                    logger.error(f"Failed to navigate to page {target_page}, skipping {potion_name}")
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
            f"{format_timestamp()} ⚠️ Luck dropped: {prev_luck} → {current_luck}. "
            "Checking buffs for replenishment..."
        )

        await self.check_buffs()
        # If check_buffs returned empty (timeout/429), retry once before acting.
        # An empty result when we know luck was high = parse failure, not genuinely no buffs.
        if not self.active_buffs and prev_luck > 1.0:
            logger.info("Buff check returned empty — retrying once before purchasing...")
            await asyncio.sleep(3.0)
            await self.check_buffs()
            if not self.active_buffs:
                logger.warning("Buff check still empty after retry — skipping replenishment to avoid over-buying")
                return

        needs = self._calculate_needs()

        if needs:
            logger.info(f"Replenishment needed: {needs}")
            # Wait for rolling rate-limits to settle before hammering the shop
            logger.info("Waiting 8s for rate limits to settle before shop...")
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
