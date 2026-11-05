import asyncio
import logging

import discord

from config import POTIONS, BOT_ID
from utils import wait_for_bot_response, get_embed_text, parse_balance, parse_balance_after

logger = logging.getLogger("timeless")

# Buy button labels → quantities, ordered largest first
BUY_BUTTON_OPTIONS = [(10, "Buy 10"), (5, "Buy 5"), (2, "Buy 2"), (1, "Buy")]

# Cache application commands per channel to avoid rate limiting
_cmd_cache: dict[int, list] = {}


async def get_application_commands(channel) -> list:
    """Fetch and cache application commands for a channel, with retry on 429."""
    if channel.id in _cmd_cache:
        return _cmd_cache[channel.id]

    for attempt in range(5):
        try:
            cmds = await channel.application_commands()
            _cmd_cache[channel.id] = cmds
            logger.debug(f"Cached {len(cmds)} app commands for channel {channel.id}")
            return cmds
        except discord.HTTPException as e:
            if e.status == 429:
                wait = 10 * (attempt + 1)
                logger.warning(f"🙀⏳ wate wimited fetching commands, waiting {wait}s (attempt {attempt+1}/5) hisss")
                await asyncio.sleep(wait)
            else:
                raise
    logger.error("😿 faiwed to fetch appwication commands aftew 5 wetwies... nyooo")
    return []


def clear_cmd_cache():
    """Clear the command cache (call if commands seem stale)."""
    _cmd_cache.clear()


async def wait_for_shop_response(
    client: discord.Client,
    channel,
    bot_id: int,
    timeout: float = 10.0,
) -> discord.Message | None:
    """Wait for a shop-specific response (purchase confirmation or shop page)."""
    SHOP_KEYWORDS = ("shop", "coins", "purchase", "page ", "balance", "bought", "item shop")

    def is_shop_msg(msg: discord.Message) -> bool:
        if msg.author.id != bot_id or msg.channel.id != channel.id:
            return False
        if not (msg.embeds or msg.content):
            return False
        text = " ".join([
            (e.description or "") + (e.footer.text or "" if e.footer else "") +
            " ".join(f.value or "" for f in e.fields)
            for e in msg.embeds
        ]).lower()
        return any(kw in text for kw in SHOP_KEYWORDS)

    def check_msg(msg: discord.Message) -> bool:
        return is_shop_msg(msg)

    def check_edit(before: discord.Message, after: discord.Message) -> bool:
        return is_shop_msg(after)

    msg_task = asyncio.create_task(
        client.wait_for("message", check=check_msg, timeout=timeout)
    )
    edit_task = asyncio.create_task(
        client.wait_for("message_edit", check=check_edit, timeout=timeout)
    )

    done, pending = await asyncio.wait(
        {msg_task, edit_task},
        return_when=asyncio.FIRST_COMPLETED,
        timeout=timeout + 1,
    )
    for t in pending:
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    for t in done:
        try:
            result = t.result()
            if isinstance(result, tuple):
                return result[1]
            return result
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    logger.warning("⏰😿 timed out waiting fow shop wesponse... mew")
    return None


class ShopInteraction:
    """Handles multi-step shop interactions using discord.py-self component API."""

    def __init__(self, client: discord.Client, channel):
        self.client = client
        self.channel = channel
        self.current_shop_message: discord.Message | None = None

    async def open_shop(self) -> discord.Message | None:
        """Send /shop and capture the shop message with components."""
        msg = await send_slash_command(self.client, self.channel, BOT_ID, "shop")
        if msg:
            self.current_shop_message = msg
            logger.info("🛒😸 shop opened successfuwwy nya~")
        else:
            logger.error("🙀 faiwed to open shop - no wesponse, nyooo")
        return msg

    async def get_balance_from_shop(self) -> int | None:
        """Open shop and extract current balance from footer."""
        msg = await self.open_shop()
        if msg is None:
            return None
        text = get_embed_text(msg)
        return parse_balance(text)

    def _find_select(self) -> discord.SelectMenu | None:
        """Find the SelectMenu in the current shop message."""
        if not self.current_shop_message:
            return None
        for row in self.current_shop_message.components:
            for child in row.children:
                if isinstance(child, discord.SelectMenu):
                    return child
        return None

    def _find_button(self, label: str) -> discord.Button | None:
        """Find a Button by exact label match."""
        if not self.current_shop_message:
            return None
        for row in self.current_shop_message.components:
            for child in row.children:
                if isinstance(child, discord.Button):
                    if (child.label or "").strip() == label:
                        return child
        return None

    def _get_current_page_items(self) -> list[str]:
        """Get the list of items currently shown in the dropdown (to detect page)."""
        select = self._find_select()
        if select is None:
            return []
        return [o.value for o in select.options]

    def _log_page_contents(self, label: str = ""):
        """Log full dropdown option details for debugging."""
        select = self._find_select()
        if select is None:
            logger.info(f"🔍🐾 [Page debug{' '+label if label else ''}] nyo dwopdown found mew")
            return
        options_info = [(o.label, o.value) for o in select.options]
        buttons = []
        if self.current_shop_message:
            for row in self.current_shop_message.components:
                for child in row.children:
                    if isinstance(child, discord.Button) and child.label:
                        buttons.append(child.label)
        logger.info(f"🔍🐾 [Page debug{' '+label if label else ''}] Options: {options_info} | Buttons: {buttons} nya~")

    async def select_dropdown_item(self, item_name: str) -> bool:
        """Select item_name from shop dropdown. Returns True on success."""
        select = self._find_select()
        if select is None:
            logger.error(f"🙀 nyo dwopdown found in shop message fow '{item_name}'... mew")
            return False

        # Find the matching option object
        target_option = None
        for option in select.options:
            if option.value == item_name or option.label == item_name:
                target_option = option
                break

        if target_option is None:
            available = [o.value for o in select.options]
            logger.warning(
                f"🙀 '{item_name}' not on cuwwent shop page. Avaiwabwe: {available} mew?"
            )
            return False

        try:
            # discord.py-self SelectMenu.choose() takes SelectOption objects
            await select.choose(target_option)
            logger.debug(f"👆 sewected '{target_option.label}' fwom dwopdown nya")
            # Wait longer for the shop bot to process the selection and edit the message
            await asyncio.sleep(2.5)
            try:
                if self.current_shop_message is not None:
                    self.current_shop_message = await self.current_shop_message.fetch()
            except Exception as e:
                logger.debug(f"😿 couldn't we-fetch shop message: {e}")
            return True
        except Exception as e:
            logger.error(f"🙀 faiwed to sewect '{item_name}' fwom dwopdown: {e} nyooo")
            return False

    async def click_button(self, label: str) -> discord.Message | None:
        """Click a button by exact label; waits for the shop message to be edited."""
        button = self._find_button(label)
        if button is None:
            available = []
            if self.current_shop_message:
                for row in self.current_shop_message.components:
                    for child in row.children:
                        if isinstance(child, discord.Button) and child.label:
                            available.append(child.label)
            logger.warning(f"🙀 button '{label}' nyot found. Avaiwabwe: {available} mew?")
            return None

        msg_id = self.current_shop_message.id if self.current_shop_message else None

        try:
            # Register the message_edit listener BEFORE clicking to avoid race condition
            # where the edit event fires before wait_for is set up.
            edit_task = None
            if msg_id:
                def check_edit(before: discord.Message, after: discord.Message) -> bool:
                    return after.id == msg_id and after.author.id == BOT_ID

                edit_task = asyncio.create_task(
                    self.client.wait_for("message_edit", check=check_edit, timeout=10.0)
                )

            await button.click()
            logger.debug(f"🐾 cwicked button: '{label}' nya~")

            if edit_task:
                try:
                    _, after = await asyncio.wait_for(edit_task, timeout=10.0)
                    self.current_shop_message = after
                    return after
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    logger.debug(f"😿 nyo edit event fow '{label}', powwing fetch()... *taps paw*")
                    edit_task.cancel()

            # Fallback: poll fetch() until content changes (handles slow updates)
            current_items = self._get_current_page_items()
            for _ in range(12):  # poll up to 6s
                await asyncio.sleep(0.5)
                try:
                    if self.current_shop_message is None:
                        break
                    fresh = await self.current_shop_message.fetch()
                    self.current_shop_message = fresh
                    new_items = self._get_current_page_items()
                    if new_items != current_items:
                        return fresh
                except Exception:
                    break

            return self.current_shop_message
        except Exception as e:
            logger.error(f"🙀 faiwed to cwick button '{label}': {e} nyooo")
            return None

    async def navigate_to_page(self, page: int) -> bool:
        """Navigate to a specific shop page (1-indexed). Verifies we reached the page."""
        if page <= 1:
            return True
        
        for click_num in range(page - 1):
            response = await self.click_button("Next page")
            if response is None:
                logger.error(f"🙀 faiwed to cwick 'Next page' whiwe nyavigating to page {page}... mew")
                return False
            self._log_page_contents(f"after click {click_num + 1}")
            await asyncio.sleep(0.5)
        
        logger.debug(f"📖😸 nyavigated to page {page} nya~")
        return True

    async def buy_item(self, item_name: str, quantity: int = 1) -> tuple[bool, int]:
        """Buy `quantity` of item using the most efficient button combos.
        Selects item once, then uses Buy/Buy 2/Buy 5/Buy 10 buttons optimally.
        Returns (success, total_coins_spent).
        
        If item is not on current page, logs warning and returns (False, 0) gracefully.
        """
        potion_info = POTIONS.get(item_name)
        if not potion_info:
            logger.error(f"🙀 unknyown potion: {item_name}... mew?")
            return False, 0

        # Check if item is even available on current page
        available_items = self._get_current_page_items()
        if item_name not in available_items:
            logger.warning(
                f"🙀 item '{item_name}' nyot avaiwabwe on cuwwent page. "
                f"Avaiwabwe: {available_items}. Skipping~ mew"
            )
            return False, 0

        total_spent = 0
        remaining = quantity

        # Select item from dropdown first
        if not await self.select_dropdown_item(item_name):
            return False, 0

        # Brief pause so any stale message-edit events from the select
        # settle before we register the listener for the Buy click.
        await asyncio.sleep(1.5)

        while remaining > 0:
            # Pick the largest buy button that fits
            chosen_qty, chosen_label = 1, "Buy"
            for qty, label in BUY_BUTTON_OPTIONS:
                if qty <= remaining and self._find_button(label) is not None:
                    chosen_qty, chosen_label = qty, label
                    break

            response = await self.click_button(chosen_label)
            if response is None:
                logger.error(f"🙀 nyo wesponse aftew cwicking '{chosen_label}' fow {item_name}... nyooo")
                return total_spent > 0, total_spent

            text = get_embed_text(response)

            # --- Determine outcome ---
            tl = text.lower()
            # Positive confirmation: the bot confirms a purchase
            is_success = any(w in tl for w in ("bought", "purchased", "you've bought", "you have bought"))
            # Explicit failure from the bot
            is_failure = any(w in tl for w in ("insufficient", "can't", "cannot", "not enough", "you don't have"))
            # Ambiguous: we got back the shop listing instead of a confirmation
            is_shop_listing = "item shop" in tl and "page " in tl and not is_success

            if is_failure:
                logger.error(f"😾 puwchase faiwed fow {item_name} — fuww wesponse:\n{text}")
                return total_spent > 0, total_spent
            if is_shop_listing and not is_success:
                logger.warning(
                    f"🙀 buy wesponse wooks wike a shop wisting (possibwe stawe edit / wate-wimit) "
                    f"fow {item_name}. Fuww text:\n{text}"
                )
                # Don't count as bought; treat as failure for this attempt
                return total_spent > 0, total_spent

            cost = potion_info["cost"] * chosen_qty
            total_spent += cost
            remaining -= chosen_qty
            logger.info(
                f"  🛍️😻 bought {chosen_qty}x {item_name} (${cost:,}) "
                f"| Pwogwess: {quantity - remaining}/{quantity} nya~"
            )

            new_bal = parse_balance(text) or parse_balance_after(text)
            if new_bal is not None:
                logger.info(f"  💰🐟 bawance aftew puwchase: ${new_bal:,} nya~")

            if remaining > 0:
                await asyncio.sleep(1.5)
                # After a purchase the shop shows the shop page again — re-select the item
                if not await self.select_dropdown_item(item_name):
                    # May need to re-open shop if message expired
                    logger.info("🛒🐾 we-opening shop to continyue puwchase...")
                    if not await self.open_shop():
                        logger.warning(f"😿 couldn't we-open shop, stopping at {quantity - remaining}/{quantity}... mew")
                        break
                    if not await self.select_dropdown_item(item_name):
                        logger.warning(f"😿 couldn't we-sewect {item_name} aftew we-open... mew")
                        break

        return True, total_spent


async def send_slash_command(
    client: discord.Client,
    channel,
    bot_id: int,
    command_name: str,
    _retries: int = 3,
    **options,
) -> discord.Message | None:
    """Invoke a slash command on the target bot and return its response.
    Retries up to _retries times on transient InvalidData / timeout errors."""
    last_error: Exception | None = None
    for attempt in range(_retries):
        if attempt > 0:
            await asyncio.sleep(2.0 * attempt)  # 2s, 4s back-off

        result = await _send_slash_command_once(client, channel, bot_id, command_name, **options)
        if result is not None:
            return result
        if last_error is not None:
            logger.warning(f"🙀 /{command_name} attempt {attempt + 1}/{_retries} faiwed: {last_error} mew")
    return None


async def _send_slash_command_once(
    client: discord.Client,
    channel,
    bot_id: int,
    command_name: str,
    **options,
) -> discord.Message | None:
    """Single attempt to invoke a slash command. Returns None on any failure."""
    try:
        cmds = await get_application_commands(channel)
        target_cmd = None
        for cmd in cmds:
            if cmd.name == command_name and cmd.application_id == bot_id:
                target_cmd = cmd
                break

        if target_cmd is None:
            logger.error(
                f"🙀 swash command '/{command_name}' nyot found fow bot {bot_id}. "
                f"Avaiwabwe: {[c.name for c in cmds if c.application_id == bot_id]} mew?"
            )
            return None

        # Register listeners BEFORE sending the command to avoid the race condition
        # where the bot responds instantly and the edit event fires before wait_for is set up.
        def check_msg(msg: discord.Message) -> bool:
            return (
                msg.author.id == bot_id
                and msg.channel.id == channel.id
                and bool(msg.embeds or msg.content)
            )

        def check_edit(before: discord.Message, after: discord.Message) -> bool:
            return (
                after.author.id == bot_id
                and after.channel.id == channel.id
                and bool(after.embeds or after.content)
            )

        def _silence_task(task: asyncio.Task) -> None:
            """Consume task exception to prevent 'Task exception was never retrieved' noise."""
            try:
                task.exception()
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

        msg_task = asyncio.create_task(
            client.wait_for("message", check=check_msg, timeout=15.0)
        )
        edit_task = asyncio.create_task(
            client.wait_for("message_edit", check=check_edit, timeout=15.0)
        )
        msg_task.add_done_callback(_silence_task)
        edit_task.add_done_callback(_silence_task)

        async def _cleanup_tasks():
            for t in (msg_task, edit_task):
                if not t.done():
                    t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass

        try:
            await target_cmd(**options)

            done, pending = await asyncio.wait(
                {msg_task, edit_task},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=16.0,
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

            for t in done:
                try:
                    result = t.result()
                    if isinstance(result, tuple):
                        return result[1]
                    return result
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

            logger.warning(f"⏰😿 timed out waiting fow bot wesponse in channew {channel.id}... mew")
            return None
        except Exception as e:
            await _cleanup_tasks()
            raise e

    except discord.errors.InvalidData as e:
        # If the current task is being cancelled, discord.py swallows CancelledError
        # and raises InvalidData instead. Re-raise properly so shutdown works cleanly.
        task = asyncio.current_task()
        if task is not None and task.cancelling() > 0:
            raise asyncio.CancelledError() from e
        logger.warning(f"😿 /{command_name} nyo Discowd ack (wiww wetwy): {e}")
        return None
    except Exception as e:
        logger.error(f"🙀 faiwed to send /{command_name}: {e} nyooo", exc_info=True)
        return None
