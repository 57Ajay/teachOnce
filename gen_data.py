"""Generate fake CSV rows for the portal. Usage: uv run gen_data.py [--rows 50] [--seed 7] [--out data/rows.csv]"""
import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

import config
import portal

FIRST = ["Asha", "Ravi", "Meera", "Kabir", "Nisha", "Arjun", "Leela", "Tara", "Imran", "Divya",
         "Farhan", "Kavya", "Rohan", "Sana", "Vikram", "Anika", "Dev", "Ira", "Neel", "Zoya"]
LAST = ["Verma", "Rao", "Kapoor", "Nair", "Sethi", "Bhatt", "Menon", "Joshi", "Qureshi", "Pillai",
        "Gill", "Dutta", "Kulkarni", "Shah", "Iyer", "Bose", "Malik", "Reddy", "Saxena", "Chawla"]
LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"
COLUMNS = ["vehicle_no", "owner_name", "vehicle_type", "from_state", "to_state", "entry_date", "tax_period", "mobile"]


def make_row(rng: random.Random, today: date) -> dict:
    from_state, to_state = rng.sample(portal.STATES, 2)
    series = "".join(rng.choices(LETTERS, k=rng.choice([1, 2])))
    return {
        "vehicle_no": f"{portal.STATE_CODES[from_state]}{rng.randint(1, 99):02d}{series}{rng.randint(1, 9999):04d}",
        "owner_name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
        "vehicle_type": rng.choice(portal.VEHICLE_TYPES),
        "from_state": from_state,
        "to_state": to_state,
        "entry_date": (today + timedelta(days=rng.randint(1, 30))).isoformat(),
        "tax_period": rng.choice(list(portal.TAX_PERIODS.values())),
        "mobile": "9" + "".join(rng.choices("0123456789", k=9)),
    }


def generate(n: int, seed: int, today: date | None = None) -> list[dict]:
    rng = random.Random(seed)
    today = today or date.today()
    return [make_row(rng, today) for _ in range(n)]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=50)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=config.DATA_DIR / "rows.csv")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(generate(args.rows, args.seed))
    print(f"wrote {args.rows} rows to {args.out}")
