import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
BOT_ID = int(os.getenv("BOT_ID", "0"))
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

# Roll timing
ROLL_DELAY = 1.5          # seconds between rolls — just under Discord's rate limit window
COOLDOWN_RETRY_DELAY = 1.5  # extra wait on cooldown hit before retry
ROLL_FAILURE_BACKOFF = 3.0  # wait after consecutive failures before trying again
BUFF_CHECK_INTERVAL = 100  # re-check buffs every N rolls regardless of luck

# Potion definitions: name -> (cost, effect_description)
POTIONS = {
    "Lucky Potion": {"cost": 1_350, "luck": 0.25, "shop_page": 1},
    "Lucky Potion+": {"cost": 8_500, "luck": 0.75, "shop_page": 1},
    "Lucky Potion++": {"cost": 20_000, "luck": 1.5, "shop_page": 1},
    "Potion of Prosperity": {"cost": 45_000, "luck": 5.0, "shop_page": 1},
    "Recursive Potion": {"cost": 42_500, "luck": 0, "aura_per_roll": 3, "shop_page": 2},
    # Placeholder values (invented) -- not in TARGET_BUFFS/PURCHASE_PRIORITY, so never auto-bought
    "idksterling": {"cost": 69_000, "luck": 2.5, "shop_page": 2},
}

# Target buff counts to maintain
TARGET_BUFFS = {
    "Lucky Potion++": 3,
    "Potion of Prosperity": 2,
    "Recursive Potion": 2,
}

# Purchase priority (highest to lowest)
PURCHASE_PRIORITY = [
    "Potion of Prosperity",
    "Lucky Potion++",
    "Lucky Potion+",
    "Lucky Potion",
    "Recursive Potion",
]

# Full setup cost (only includes potions in TARGET_BUFFS)
FULL_SETUP_COST = sum(
    TARGET_BUFFS.get(name, 0) * info["cost"]
    for name, info in POTIONS.items()
    if name in TARGET_BUFFS
)

# Relevant potion names we care about (ignore others in inventory/buffs)
RELEVANT_POTIONS = set(POTIONS.keys())

# Slash command names (application command IDs will be resolved at runtime)
CMD_ROLL = "roll"
CMD_BUFFS = "buffs"
CMD_INVENTORY = "inventory"
CMD_USEITEM = "useitem"
CMD_SHOP = "shop"
