import re
import asyncio
import logging
from datetime import datetime

import discord

logger = logging.getLogger("timeless")


async def wait_for_bot_response(
    client: discord.Client,
    channel,
    bot_id: int,
    timeout: float = 15.0,
) -> discord.Message | None:
    """Wait for a substantive response from the bot.

    Handles two patterns observed in the wild:
    - Direct message with embeds (e.g. /roll, /useitem)
    - Empty BOT MESSAGE immediately followed by BOT MESSAGE EDIT with content
      (e.g. /shop, /inventory, /buffs, /profile, etc.)

    Returns the first message that actually has embeds or content.
    Empty placeholder messages are ignored.
    """
    # We race two wait_for coroutines: one for new messages, one for edits.
    # discord.py-self supports client.wait_for() natively.
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
            # message_edit returns (before, after) tuple
            if isinstance(result, tuple):
                return result[1]
            return result
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    logger.warning(f"⏰😿 timed out waiting fow bot wesponse in channew {channel.id}... mew")
    return None


# Keep alias for any callers that still use the old name
wait_for_bot_response_any = wait_for_bot_response


def strip_md(text: str) -> str:
    """Strip common Discord markdown so regexes work on plain text."""
    text = re.sub(r"\*+", "", text)          # bold / italic
    text = re.sub(r"`+", "", text)           # code
    text = re.sub(r"^-#\s*", "", text, flags=re.MULTILINE)  # subtext
    text = re.sub(r"^>\s*-?\s*", "", text, flags=re.MULTILINE)  # blockquote
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)   # headings
    return text


def parse_balance(text: str) -> int | None:
    """Extract coin balance. Handles:
    - Shop footer: 'your balance: $341,644 coins'
    - /profile field: 'Coins: $341,644'
    - /inventory Coin block: '### **Coin**\\n-# **×341,644**'
    """
    patterns = [
        r"your balance:\s*\$([\d,]+)",          # shop footer
        r"Coins?:\s*\$\s*([\d,]+)",             # profile field
        r"(?m)Coin\b[^\n]*\n[^\n×]*×\*{0,2}([\d,]+)",  # inventory block
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return int(m.group(1).replace(",", ""))
    return None


def parse_balance_after(text: str) -> int | None:
    """Extract the 'after' balance from a purchase response like '$X → $Y'."""
    m = re.search(r"→\s*\$?\s*([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def parse_auras(text: str) -> list[dict]:
    """Parse auras from roll response.
    Actual format: '> - **Common** [ 1 in 2 ]'
    Strip markdown first so 'Common [ 1 in 2 ]' is plain.
    """
    clean = strip_md(text)
    auras = []
    SKIP = {"roll", "rolls", "coins earned", "luck"}
    for m in re.finditer(r"([\w][\w\s:]+?)\s*\[\s*1\s+in\s+([\d,]+)\s*\]", clean):
        name = m.group(1).strip()
        if name.lower() in SKIP:
            continue
        rarity = int(m.group(2).replace(",", ""))
        auras.append({"name": name, "rarity": rarity})
    return auras


def parse_roll_number(text: str) -> int | None:
    """Extract roll number. Actual format: '**Roll**: #4,767'"""
    # Match 'Roll:' followed by '#number', ignore '# You rolled' heading
    m = re.search(r"\*{0,2}Roll\*{0,2}:\s*#\s*([\d,]+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def parse_coins_earned(text: str) -> int | None:
    """Extract coins earned. Actual format: '**Coins earned:** +$5 (Total: $341,644)'"""
    m = re.search(r"\+\$\s*([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def parse_luck_value(text: str) -> float | None:
    """Extract luck value. Actual format: '**Luck:** 1'"""
    clean = strip_md(text)
    m = re.search(r"Luck:\s*([\d.]+)", clean, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def parse_buffs(text: str) -> dict:
    """Parse /buffs response → {buff_name: remaining_info}.

    Actual format (after strip_md):
        Recursive Potion
        - Rolls +3 additional auras per /roll.
        - Expires in: 109 rolls
        Potion of Prosperity
        - Gives +5 luck.
        - Expires in: 125 rolls
    """
    clean = strip_md(text)
    buffs = {}
    lines = clean.split('\n')
    for i, raw_line in enumerate(lines):
        name = raw_line.strip()
        # Buff name: starts with capital, contains only letters/digits/spaces/+, no emojis
        if not re.match(r'^[A-Z][A-Za-z0-9\s+]*$', name):
            continue
        if '<' in name or ':' in name:
            continue
        # Look ahead up to 4 lines for "Expires in:"
        for j in range(i + 1, min(i + 5, len(lines))):
            m = re.search(r'Expires in:\s*([\d\w\s]+)', lines[j], re.IGNORECASE)
            if m:
                buffs[name] = m.group(1).strip()
                break
    return buffs


def parse_inventory(text: str) -> tuple[dict[str, int], int]:
    """Parse /inventory response.
    Actual format:
        ### **Coin**
        -# **×341,644**
        ### **Lucky Potion++**
        -# **×2**
    Returns (items_dict, coin_balance).
    """
    items: dict[str, int] = {}
    balance = 0
    # Each item block: ### **Name** then a count line containing ×N
    for m in re.finditer(
        r"###\s+\*{0,2}([^*\n]+?)\*{0,2}\s*\n[^\n×x]*[×x]\*{0,2}\s*([\d,]+)",
        text,
    ):
        name = m.group(1).strip()
        count = int(m.group(2).replace(",", ""))
        if name == "Coin":
            balance = count
        else:
            items[name] = count
    return items, balance


def parse_useitem_response(text: str) -> tuple[bool, str | None]:
    """Parse /useitem response. Returns (success, expires_info).
    Actual format: 'You used 1 **Potion of Prosperity**.\\n- **Expires in:** 125 rolls'
    """
    success = "used" in text.lower()
    expires = None
    m = re.search(r"Expires in:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        expires = m.group(1).strip()
    return success, expires


def format_timestamp() -> str:
    return datetime.now().strftime("[%H:%M:%S]")


def compact_aura_str(auras: list[dict]) -> str:
    if not auras:
        return "None"
    return " ".join(f"{a['name']}[1/{a['rarity']:,}]" for a in auras)


def get_embed_text(message: discord.Message) -> str:
    """Extract all text content from a message including embeds."""
    parts = []
    if message.content:
        parts.append(message.content)
    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        for field in embed.fields:
            parts.append(f"{field.name}: {field.value}")
        if embed.footer and embed.footer.text:
            parts.append(embed.footer.text)
    return "\n".join(parts)
