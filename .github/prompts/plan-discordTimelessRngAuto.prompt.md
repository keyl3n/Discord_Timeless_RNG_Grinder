# Plan: Discord Timeless RNG Self-Bot Automation

**TL;DR:** Build a Python self-bot using `discord.py` that automatically performs `/roll` commands with intelligent potion management. On startup, check `/buffs` and `/inventory` to see what's already active/available, then use inventory potions first before buying from shop based on priority order. If balance insufficient for full setup, use priority-based purchasing (Potion of Prosperity > Lucky Potion++ > Lucky Potion+ > Lucky Potion > Recursive Potion). Fallback to rolling without buffs if needed. On shutdown (Ctrl+C), fetch final balance and generate session summary with aura counts, profit/loss, and ratio.

## Steps

### Phase 1: Project Setup & Core Infrastructure
1. Initialize Python project with `discord.py` (or `discum` if raw user account API needed), `discord-py-interactions` for component handling, and logging
2. Create `.env` file for user token and bot configuration
3. Setup main bot client and event handlers (on_ready, on_message_edit for ephemeral/public detection)
4. Create modular structure: `config.py`, `shop.py`, `potions.py`, `roller.py`, `utils.py`

### Phase 2: Intelligent Startup & Buff Management
5. On bot start: Execute startup sequence in order:
   - Send `/buffs` command and parse active buffs (format: `Buff Name`, `Expires in: X rolls/minutes`)
   - Send `/inventory` command and parse available potions (format: `Item Name × count`, with "Effect" and "Duration" lines)
   - Extract balance from inventory response (`Coin ×AMOUNT`)
   - **Register initial balance** in session state for later summary comparison
   - **Log startup state**: `[HH:MM:SS] ✅ Bot initialized | Balance: $X | Active buffs: [list] | Inventory potions: [list]`

6. **Handle edge case: User balance is $0**
   - If balance = $0 AND no inventory potions available:
     - Log warning: `⚠️ Balance is $0 and no potions in inventory. Rolling without buffs.`
     - Skip to Phase 4 (Rolling Loop) with no buffs enabled
     - Disable replenishment logic (can't buy potions if $0)
     - Run until first successful roll (should earn coins)
   - If balance = $0 BUT inventory has potions:
     - Consume available potions via `/useitem` (prioritize same as phase 7)
     - Proceed to rolling with whatever buffs are active
   - If balance > $0 but < $1,350 (minimum potion):
     - Attempt to roll a few times to build capital
     - After earning enough (>$1,350), proceed to phase 7 purchasing logic
     - If can't earn enough after 10 rolls, log warning and continue rolling without buffs

7. **Calculate required potion setup:**
   - Target state: 3x Lucky Potion++ active, 2x Potion of Prosperity active, 2x Recursive Potion active
   - Compare against `/buffs` response to see what's already active and remaining duration
   - Compare against `/inventory` to see what potions are available (unused)
   - Calculate purchase needs based on gaps

8. **Intelligent purchasing strategy** (if balance < $255,000 required):
   - First: Check if unused potions in inventory can be consumed via `/useitem` to meet requirements
   - If inventory has potions, use them first (max 1 of each type to avoid over-buffing)
   - Then: Calculate remaining needs and check balance
   - If balance insufficient for full setup, use priority order to buy what we can:
     1. Potion of Prosperity ($45,000, +5 luck) — highest priority
     2. Lucky Potion++ ($20,000, +1.5 luck)
     3. Lucky Potion+ ($8,500, +0.75 luck)
     4. Lucky Potion ($1,350, +0.25 luck)
     5. Recursive Potion ($42,000, +3 aura/roll) — lowest priority (needs luck to be effective)
   - Buy what's affordable, use available potions, then proceed with reduced setup
   - If still insufficient to meet ANY viable buff setup, log warning and proceed to rolling without buffs
   - **Log purchasing decision**: `[HH:MM:SS] 📊 Purchasing plan | Buying: [items] | Cost: $X | Remaining balance: $Y`

9. Create `ShopInteraction` class to handle multi-step shop interactions:
   - Click dropdown via component interaction (component_id structure: likely `shop_dropdown_1` or similar)
   - Select items by label from dropdown options
   - Click appropriate Buy buttons (component IDs vary: `buy_1`, `buy_2`, etc.)
   - Wait for confirmation response (coin deduction, item count update)

### Phase 3: Potion Purchase & Consumption Logic
10. Implement shop flow for **Page 1 (first 5 potions)**:
   - Click dropdown → select "Lucky Potion++" → click Buy → click Buy 2 → wait for response → repeat until 3x purchased
   - Parse purchase response (ephemeral, "Only you can see this"):
     ```
     ✅ Purchase successful
     Coins: $X → $Y
     Amount spent: $Z
     [Item Name]: [before] → [after]
     Total purchased: [count]
     ```
   - Click dropdown → select "Potion of Prosperity" → click Buy 2 → wait for response → repeat until 2x purchased
11. Implement shop navigation to **Page 2**: Click "Next page" button → wait for page load
12. Implement shop flow for **Page 2**:
    - Click dropdown → select "Recursive Potion" (NOT Refined) → click Buy 2 → wait for response → repeat until 2x purchased
13. **Consume purchased potions** with `/useitem` commands (execute based on purchase needs):
    - Use `/useitem item:Lucky Potion++ amount:X` (where X = purchased quantity, max 3 per startup)
    - Use `/useitem item:Potion of Prosperity amount:X` (where X = purchased quantity, max 2 per startup)
    - Use `/useitem item:Recursive Potion amount:X` (where X = purchased quantity, max 2 per startup)
    - Parse responses for "Expires in: N rolls" or "Expires in: N minutes" to confirm activation
14. Track active buff states: `{buff_name: remaining_duration_or_rolls}` updated from `/buffs` responses or `/roll` output (Luck: X)

### Phase 4: Rolling Loop & Response Handling
15. Implement main rolling loop:
    - Send `/roll` command
    - Wait for response from Timeless RNG bot (message from bot_id `#5772`, or use presence/embed detection)
    - **Handle cooldown response** ("Cooldown reached\nYou can only roll once every 1.5 seconds"):
      - Log cooldown warning
      - Wait additional 1-2 seconds and retry `/roll`
    - Parse response for auras (e.g., "Aquamarine [ 1 in 900 ]", "Good [ 1 in 5 ]", etc.)
    - Extract roll number, coins earned, luck value, and final luck effect from response
    - Detect if message is ephemeral ("Only you can see this") vs public
    - **Log aura data to JSON file** (append roll with timestamp, auras list, coins, luck)
    - Log compact roll data to terminal
16. After each roll response, check if any active buff duration has expired:
    - Parse `/buffs` response OR infer from `/roll` response output (Luck: X value change)
    - If Lucky Potion++ expires (luck drops from 7.5 to 6), trigger purchase of 3 more
    - If Potion of Prosperity expires (luck drops from 5+ to 1), trigger purchase of 2 more
    - If Recursive Potion expires (aura count changes), trigger purchase of 2 more

### Phase 5: Error Handling & Resilience
17. Implement retry logic:
    - Rate limit handling (wait 1.5-3s between /roll commands per Discord cooldown)
    - Failed button clicks → retry with exponential backoff
    - Shop session expiration → restart shop flow if component no longer valid
    - Balance check before replenishment purchases (stop if balance < replenish cost)
18. **Implement graceful shutdown handler** (Ctrl+C):
    - Catch `KeyboardInterrupt` signal
    - Send `/shop` command to fetch final balance
    - Parse final balance from response
    - Calculate balance change: `final_balance - initial_balance`
    - Load all rolls from JSON stats file
    - Generate summary report (see Phase 6 for format)
    - Log summary to terminal and save to `session_summary.txt`
    - Clean exit
19. Logging: Terminal output showing timestamps, balance before/after, active buffs, roll results (public only), replenishment triggers
   - **Compact roll log format** (per roll response):
     ```
     [HH:MM:SS] Roll #3,859 | Auras: Aquamarine[1/900] Good[1/5] Divinus[1/32] Good[1/5] Rare[1/16] Tuff[1/67] | Coins: +$900 (Total: $255,846) | Luck: 6 | Windy (Nighttime) x1
     ```
   - **Replenishment log format** (when buff expires):
     ```
     [HH:MM:SS] ⚠️ Lucky Potion++ expired (luck: 7.5 → 6) | Replenishing: 3x Lucky Potion++ | New balance: $175,846 | Buff expires in: 5 min
     ```

### Phase 6: Testing & Verification
20. **Implement session summary generation** (triggered on graceful shutdown):
   - Aggregate all auras from JSON stats file into counts by rarity type
   - Output format:
     ```
     ========== SESSION SUMMARY ==========
     [Timestamp: HH:MM:SS - HH:MM:SS]
     
     Auras collected:
     3x Divinus (1 in 32)
     1x Rare (1 in 16)
     3x Natural (1 in 8)
     3x Good (1 in 5)
     3x Uncommon (1 in 4)
     14x Common (1 in 2)
     
     Stats:
     Total Rolls: 42
     Total Coins Earned: $39,650
     Total Coins Spent: $85,000 (replenishment potions)
     Spent:Earned Ratio: 2.14:1
     Net Profit/Loss: -$45,350
     Initial Balance: $299,946
     Final Balance: $254,596
     ```
   - Save to `session_summary.txt` in project directory
   - Log to terminal before exit
21. Manual verification:
    - Test startup balance check with insufficient balance (should log and stop)
    - Test single shop purchase flow for one potion type
    - Test multi-page shop navigation
    - Test `/useitem` consumption and buff parsing
    - Test rolling loop with manual `/buffs` checks
    - Verify ephemeral vs public roll detection
    - **Test cooldown handling** (send /roll too fast, verify bot waits and retries)
    - Test Ctrl+C graceful shutdown → verify final balance check and summary generated
    - Verify JSON stats file populated correctly after 10+ rolls
    - Verify summary matches aura counts and balance calculations

## Relevant Files
- `main.py` — Entry point, initializes bot, starts rolling loop, handles graceful shutdown
- `config.py` — Constants: potion costs, durations, bot IDs, component IDs (reverse-engineered)
- `shop.py` — `ShopInteraction` class handling dropdown selection, button clicks, purchase confirmations
- `potions.py` — `PotionManager` class tracking active buffs, triggering replenishment logic
- `roller.py` — Main loop, `/roll` sending, response parsing, buff expiration detection, cooldown handling
- `stats.py` — `StatsManager` class for JSON logging, aura aggregation, summary generation
- `utils.py` — Helpers: balance regex parsing, message waiting, component ID resolution, compact logging formatters
- `rolls.json` — Persistent JSON file storing each roll: timestamp, auras, coins earned, luck value
- `session_summary.txt` — Generated on shutdown, contains aura counts, balance comparison, profit/loss summary

## Verification
1. Run bot with mock balance < $255,000 → verify terminal logs "Insufficient balance" and bot stops
2. Run bot with sufficient balance → verify `/shop` → Buy 3x Lucky Potion++, 2x Prosperity, 2x Recursive in correct order
3. Verify `/useitem` responses are parsed correctly and buff states logged
4. Run rolling loop for 30+ rolls → verify buff durations tracked, Luck values logged, ephemeral detection working
5. Trigger a buff expiration scenario → verify replenishment purchase initiated automatically

## Decisions
- **Tech Stack:** Python + `discord.py` for self-bot support and ease of automation
- **Component Interaction:** Reverse-engineer Discord component IDs from network requests (inspect via DevTools when running bot, or log raw interactions)
- **Buff Tracking:** Parse from `/roll` response output (Luck: X) and `/buffs` command to avoid calculating; real user-initiated rolls may have carried-over buffs
- **Scope Included:** Balance check, multi-item shop purchases, potion consumption, roll loop, buff expiration detection, replenishment logic
- **Scope Excluded:** Advanced error recovery (e.g., if shop crashes mid-transaction), analytics/statistics beyond logging, GUI dashboard

## Further Considerations
1. **Component ID Discovery** — Discord component IDs are ephemeral and change per session. Strategy: Log raw interaction payloads during first shop run to identify the pattern, then hardcode or dynamically extract from response embeds.
2. **Startup State Detection** — On startup, check `/buffs` and `/inventory` to understand current potion state. Parse formats:
   - `/buffs`: `[buff_name]\nGives/Rolls [effect]\nExpires in: [N rolls|N minutes]`
   - `/inventory`: `[item_name]\n×[count]\nEffect: [description]\nDuration: [description]`
   - Only consider these potions for use: Lucky Potion, Lucky Potion+, Lucky Potion++, Potion of Prosperity, Recursive Potion. Ignore all others.
3. **Inventory-Based Purchasing Logic** — If balance < full setup cost ($255,000):
   - Use available inventory potions first (via `/useitem`)
   - Then buy remaining needs in priority order
   - If can't afford any full potion type, buy the cheapest (Lucky Potion at $1,350) and roll with minimal buffs
   - If balance < $1,350 AND no inventory potions available, proceed to rolling without buffs (log warning: "Starting without buffs; balance insufficient")
4. **Fallback Rolling Mode & Zero Balance Case** — If startup balance/inventory can't support recommended buff setup, bot can still run:
   - **If balance = $0 with no potions**: Log warning: `⚠️ Balance is $0 with no available potions. Rolling without buffs to build capital.` Disable replenishment logic entirely. After first few successful rolls, if balance > $1,350, resume normal purchasing logic.
   - **If balance > $0 but < $1,350**: Roll 5-10 times to accumulate coins. If balance reaches > $1,350 after earning, proceed to phase 7 purchasing. If still insufficient after 10 rolls, proceed without buffs.
   - **General fallback**: Log warning: "Insufficient funds for recommended setup. Rolling without buffs."
   - Disable replenishment logic (don't buy potions during rolling in fallback mode)
   - Continue rolling until user manually stops (Ctrl+C)
   - On shutdown, summary will show 0 potions used and 0x multiplier on luck if in full fallback mode, or partial buffs if balance was limited
5. **Luck Value Parsing Edge Cases** — When multiple potions active, "Luck: 7.5" from `/roll` response combines all sources. Use `/buffs` as ground truth for buff sources if reconciliation needed.
6. **Rate Limiting & Cooldown Precision** — Handle cooldown response: `:info: Cooldown reached\nYou can only roll once every 1.5 seconds.` → wait 1-2s and retry. Use fixed 3s between rolls to minimize rate limit risk.
7. **Purchase Confirmation Parsing** — After each purchase, verify response contains updated coin balance (e.g., "$299,946 → $254,946") and item count increment ("Potions of Prosperity: 0 → 1") to confirm successful transaction.
8. **Graceful Shutdown Balance Reconciliation** — Initial balance captured at startup, final balance fetched via `/shop` on Ctrl+C. Difference should account for all purchases and roll earnings. If mismatch > $1,000, log warning before generating summary.
