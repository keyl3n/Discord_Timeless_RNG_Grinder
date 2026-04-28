
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("timeless")

ROLLS_FILE = Path("rolls.json")
SUMMARY_FILE = Path("session_summary.txt")


def _load_data() -> dict:
    if ROLLS_FILE.exists():
        try:
            with open(ROLLS_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, dict) and "all_time" in data:
                return data
        except Exception:
            pass
    return {
        "all_time": {
            "total_rolls": 0,
            "total_coins_earned": 0,
            "total_coins_spent": 0,
            "auras": {},
        },
        "sessions": [],
    }


def _save_data(data: dict):
    try:
        with open(ROLLS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to write rolls.json: {e}")


class StatsManager:
    def __init__(self):
        self.session_start = datetime.now()
        self.initial_balance: int = 0

        self._session_rolls: int = 0
        self._session_coins_earned: int = 0
        self._session_coins_spent: int = 0
        self._session_auras: dict[str, dict] = {}

        self._data = _load_data()

    def set_initial_balance(self, balance: int):
        self.initial_balance = balance

    def record_roll(self, roll_number: int | None, auras: list[dict], coins_earned: int, luck: float | None):
        self._session_rolls += 1
        self._session_coins_earned += coins_earned

        at = self._data["all_time"]
        at["total_rolls"] += 1
        at["total_coins_earned"] += coins_earned

        for aura in auras:
            name = aura["name"]
            rarity = aura["rarity"]
            # session
            if name in self._session_auras:
                self._session_auras[name]["count"] += 1
            else:
                self._session_auras[name] = {"rarity": rarity, "count": 1}
            # all-time
            if name in at["auras"]:
                at["auras"][name]["count"] += 1
            else:
                at["auras"][name] = {"rarity": rarity, "count": 1}

        _save_data(self._data)

    def record_purchase(self, amount: int):
        self._session_coins_spent += amount
        self._data["all_time"]["total_coins_spent"] += amount
        _save_data(self._data)

    def generate_summary(self, final_balance: int | None) -> str:
        session_end = datetime.now()

        sorted_session = sorted(
            self._session_auras.items(),
            key=lambda kv: kv[1]["rarity"],
            reverse=True,
        )

        net = self._session_coins_earned - self._session_coins_spent
        net_str = f"+${net:,}" if net >= 0 else f"-${abs(net):,}"
        ratio_str = (
            f"{self._session_coins_spent / self._session_coins_earned:.2f}:1"
            if self._session_coins_earned > 0 else "N/A"
        )
        if final_balance is not None:
            final_bal_str = f"${final_balance:,}"
        elif self.initial_balance > 0:
            estimated = self.initial_balance + self._session_coins_earned - self._session_coins_spent
            final_bal_str = f"${estimated:,} (estimated)"
        else:
            final_bal_str = "Unknown"

        # Append this session to the file
        session_entry = {
            "start": self.session_start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": session_end.strftime("%Y-%m-%d %H:%M:%S"),
            "rolls": self._session_rolls,
            "coins_earned": self._session_coins_earned,
            "coins_spent": self._session_coins_spent,
            "start_balance": self.initial_balance,
            "end_balance": final_balance,
            "auras": {
                name: {"rarity": v["rarity"], "count": v["count"]}
                for name, v in sorted(
                    self._session_auras.items(),
                    key=lambda kv: kv[1]["rarity"],
                    reverse=True,
                )
            },
        }
        self._data["sessions"].append(session_entry)
        _save_data(self._data)

        at = self._data["all_time"]
        at_sorted = sorted(at["auras"].items(), key=lambda kv: kv[1]["rarity"], reverse=True)

        lines = [
            "========== SESSION SUMMARY ==========",
            f"[{self.session_start.strftime('%H:%M:%S')} - {session_end.strftime('%H:%M:%S')}]",
            "",
            "Auras this session:",
        ]
        if sorted_session:
            for name, a in sorted_session:
                lines.append(f"  {a['count']}x {name} (1 in {a['rarity']:,})")
        else:
            lines.append("  None")

        lines.extend([
            "",
            "Session stats:",
            f"  Rolls:         {self._session_rolls:,}",
            f"  Coins earned:  ${self._session_coins_earned:,}",
            f"  Coins spent:   ${self._session_coins_spent:,}",
            f"  Net:           {net_str}",
            f"  Spent:Earned:  {ratio_str}",
            f"  Start balance: ${self.initial_balance:,}",
            f"  End balance:   {final_bal_str}",
            "",
            "========== ALL-TIME ==========",
            f"  Total rolls:        {at['total_rolls']:,}",
            f"  Total coins earned: ${at['total_coins_earned']:,}",
            f"  Total coins spent:  ${at['total_coins_spent']:,}",
            f"  Sessions logged:    {len(self._data['sessions'])}",
            "",
            "All-time auras (top 20 rarest):",
        ])
        for name, a in at_sorted[:20]:
            lines.append(f"  {a['count']:,}x {name} (1 in {a['rarity']:,})")

        summary = "\n".join(lines)
        try:
            with open(SUMMARY_FILE, "w") as f:
                f.write(summary)
        except Exception as e:
            logger.error(f"Failed to write session_summary.txt: {e}")

        return summary
