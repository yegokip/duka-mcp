"""
Duka MCP Server: an AI assistant for a small shop.

Lets an AI app (Claude Desktop, etc.) manage a shop in plain conversation:
  - Inventory and sales (check stock, record sales, restock)
  - WhatsApp (ready-to-send supplier orders and daily reports)
  - Dashboard (a clean HTML page of takings, stock levels and best sellers)

Data lives in a local SQLite file (duka.db), created and seeded on first run.

Setup:
    pip install "mcp[cli]<2"
    python server.py          # runs over stdio, which is what Claude Desktop uses

Optional: set DUKA_SHOP_NAME in the environment to put your shop's name on
WhatsApp messages and the dashboard.
"""

import html
import os
import sqlite3
import webbrowser
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "duka.db"
DASHBOARD_PATH = BASE_DIR / "dashboard.html"
SHOP_NAME = os.environ.get("DUKA_SHOP_NAME", "Duka")

mcp = FastMCP("duka-shop-assistant")


# ---------- database helpers ----------

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables and seed sample Nairobi shop stock on first run."""
    with get_db() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS inventory (
                   item TEXT PRIMARY KEY,
                   quantity INTEGER NOT NULL,
                   price_kes REAL NOT NULL,
                   reorder_level INTEGER NOT NULL DEFAULT 10
               )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS sales (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   sale_date TEXT NOT NULL,
                   item TEXT NOT NULL,
                   quantity INTEGER NOT NULL,
                   total_kes REAL NOT NULL
               )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS suppliers (
                   name TEXT PRIMARY KEY,
                   phone TEXT NOT NULL,
                   items TEXT NOT NULL
               )"""
        )
        if db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO inventory VALUES (?, ?, ?, ?)",
                [
                    ("maize flour 2kg", 40, 150, 15),
                    ("sugar 1kg", 8, 160, 10),
                    ("cooking oil 1L", 25, 320, 10),
                    ("milk 500ml", 12, 65, 20),
                    ("bread", 30, 60, 15),
                    ("rice 1kg", 6, 180, 10),
                    ("tea leaves 250g", 18, 120, 8),
                ],
            )


# ---------- WhatsApp helpers ----------

def clean_phone(raw: str) -> str:
    """Turn '0712 345 678' or '+254712345678' into '254712345678' for wa.me links."""
    digits = "".join(c for c in raw if c.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "71":
        digits = "254" + digits
    return digits


def whatsapp_link(phone: str, message: str) -> str:
    """A click-to-chat link: opens WhatsApp with the message already typed."""
    return f"https://wa.me/{clean_phone(phone)}?text={quote(message)}"


def order_quantity(row: sqlite3.Row) -> int:
    """Suggest topping up to twice the reorder level."""
    return max(row["reorder_level"] * 2 - row["quantity"], row["reorder_level"])


def sales_for_day(db: sqlite3.Connection, day: str) -> list[sqlite3.Row]:
    return db.execute(
        """SELECT item, SUM(quantity) AS units, SUM(total_kes) AS revenue
           FROM sales WHERE sale_date = ? GROUP BY item ORDER BY revenue DESC""",
        (day,),
    ).fetchall()


# ---------- inventory and sales tools ----------

@mcp.tool()
def check_stock(item: str) -> str:
    """Check how many units of an item are in stock and its price in KES.
    Matches partial names, e.g. 'sugar' finds 'sugar 1kg'."""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM inventory WHERE item LIKE ?", (f"%{item.lower()}%",)
        ).fetchall()
    if not rows:
        return f"No item matching '{item}' found in inventory."
    return "\n".join(
        f"{r['item']}: {r['quantity']} in stock, KES {r['price_kes']:.0f} each"
        for r in rows
    )


@mcp.tool()
def low_stock_report() -> str:
    """List all items at or below their reorder level, so the owner knows what to restock."""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM inventory WHERE quantity <= reorder_level ORDER BY quantity"
        ).fetchall()
    if not rows:
        return "All items are well stocked."
    return "Items to restock:\n" + "\n".join(
        f"- {r['item']}: {r['quantity']} left (reorder at {r['reorder_level']})"
        for r in rows
    )


@mcp.tool()
def record_sale(item: str, quantity: int) -> str:
    """Record a sale: reduces stock and logs the revenue. Use the exact item name."""
    if quantity <= 0:
        return "Quantity must be greater than zero."
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM inventory WHERE lower(item) = ?", (item.lower(),)
        ).fetchone()
        if row is None:
            return f"'{item}' not found. Use check_stock to find the exact name."
        if row["quantity"] < quantity:
            return f"Only {row['quantity']} of {row['item']} in stock; sale not recorded."
        total = row["price_kes"] * quantity
        db.execute(
            "UPDATE inventory SET quantity = quantity - ? WHERE item = ?",
            (quantity, row["item"]),
        )
        db.execute(
            "INSERT INTO sales (sale_date, item, quantity, total_kes) VALUES (?, ?, ?, ?)",
            (date.today().isoformat(), row["item"], quantity, total),
        )
    return f"Sold {quantity} x {row['item']} for KES {total:.0f}."


@mcp.tool()
def get_daily_sales(day: str = "") -> str:
    """Summarize sales for a day (format YYYY-MM-DD). Defaults to today."""
    day = day or date.today().isoformat()
    with get_db() as db:
        rows = sales_for_day(db, day)
    if not rows:
        return f"No sales recorded for {day}."
    total = sum(r["revenue"] for r in rows)
    lines = [f"{r['item']}: {r['units']} units, KES {r['revenue']:.0f}" for r in rows]
    return f"Sales for {day}:\n" + "\n".join(lines) + f"\nTotal: KES {total:.0f}"


@mcp.tool()
def restock(item: str, quantity: int) -> str:
    """Add newly delivered units to an item's stock."""
    if quantity <= 0:
        return "Quantity must be greater than zero."
    with get_db() as db:
        row = db.execute(
            "SELECT item FROM inventory WHERE lower(item) = ?", (item.lower(),)
        ).fetchone()
        if row is None:
            return f"'{item}' not found. Use check_stock to find the exact name."
        db.execute(
            "UPDATE inventory SET quantity = quantity + ? WHERE item = ?",
            (quantity, row["item"]),
        )
        new_qty = db.execute(
            "SELECT quantity FROM inventory WHERE item = ?", (row["item"],)
        ).fetchone()[0]
    return f"Restocked {row['item']}: now {new_qty} units."


# ---------- WhatsApp tools ----------

@mcp.tool()
def add_supplier(name: str, phone: str, items: str) -> str:
    """Save a supplier so restock orders can go to them on WhatsApp.
    `items` is a comma-separated list of words that match the products they
    supply, e.g. 'milk, bread'. Phone can be written as 0712345678 or +254712345678."""
    if len(clean_phone(phone)) < 11:
        return f"'{phone}' doesn't look like a full phone number."
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO suppliers (name, phone, items) VALUES (?, ?, ?)",
            (name, clean_phone(phone), items.lower()),
        )
    return f"Saved supplier {name} ({clean_phone(phone)}) for: {items}."


@mcp.tool()
def whatsapp_restock_messages() -> str:
    """Build ready-to-send WhatsApp orders for every low-stock item, grouped by
    supplier. Each result includes a link that opens WhatsApp with the message
    already typed, so the owner only has to tap send."""
    with get_db() as db:
        low = db.execute(
            "SELECT * FROM inventory WHERE quantity <= reorder_level ORDER BY item"
        ).fetchall()
        suppliers = db.execute("SELECT * FROM suppliers").fetchall()
    if not low:
        return "Nothing is low on stock, so there is nothing to order."

    orders: dict[str, list[sqlite3.Row]] = {}
    unmatched: list[str] = []
    for row in low:
        match = next(
            (
                s
                for s in suppliers
                if any(k.strip() and k.strip() in row["item"].lower() for k in s["items"].split(","))
            ),
            None,
        )
        if match is None:
            unmatched.append(row["item"])
        else:
            orders.setdefault(match["name"], []).append(row)

    by_name = {s["name"]: s for s in suppliers}
    parts = []
    for name, rows in orders.items():
        lines = "\n".join(f"- {order_quantity(r)} x {r['item']}" for r in rows)
        message = (
            f"Hello {name}, this is {SHOP_NAME}. Please can we order:\n{lines}\n"
            "Kindly confirm the price and delivery time. Thank you!"
        )
        parts.append(
            f"To {name}:\n{message}\nOpen in WhatsApp: "
            f"{whatsapp_link(by_name[name]['phone'], message)}"
        )
    if unmatched:
        parts.append(
            "No supplier saved for: " + ", ".join(unmatched)
            + ". Use add_supplier to add one."
        )
    return "\n\n".join(parts)


@mcp.tool()
def whatsapp_daily_report(phone: str) -> str:
    """Build today's sales report as a WhatsApp message for the owner (or a
    partner). Returns a link that opens WhatsApp with the report ready to send."""
    today = date.today().isoformat()
    with get_db() as db:
        rows = sales_for_day(db, today)
        low = db.execute(
            "SELECT item FROM inventory WHERE quantity <= reorder_level"
        ).fetchall()
    total = sum(r["revenue"] for r in rows)
    sold = "\n".join(f"- {r['item']}: {r['units']} sold" for r in rows) or "- No sales yet"
    low_line = ", ".join(r["item"] for r in low) if low else "none"
    message = (
        f"{SHOP_NAME} report for {today}\n"
        f"Total sales: KES {total:,.0f}\n{sold}\n"
        f"Running low: {low_line}"
    )
    return f"{message}\n\nOpen in WhatsApp: {whatsapp_link(phone, message)}"


# ---------- dashboard ----------

DASHBOARD_CSS = """
:root{--bg:#F6F8FB;--panel:#FFFFFF;--ink:#14213D;--muted:#566176;--line:#D8E0EB;
--ok:#2F7D57;--low:#E9A400;--lowtext:#14213D;--bar:#1F3A8A;--bar2:#C9D4EE}
@media (prefers-color-scheme:dark){:root{--bg:#0E1626;--panel:#152036;--ink:#E8EEF8;
--muted:#9AA7BC;--line:#26344D;--ok:#5CC08F;--low:#F2B93B;--lowtext:#0E1626;
--bar:#7C98F2;--bar2:#2A3B63}}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;padding:clamp(16px,4vw,40px);max-width:1040px;margin-inline:auto;
font-family:"Avenir Next","Trebuchet MS",system-ui,sans-serif;color:var(--ink);
background:var(--bg);line-height:1.5}
header{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
h1{font-size:1.1rem;font-weight:700;margin:0}
.date{color:var(--muted);margin:0;font-size:.95rem}
.lede{font-size:clamp(1.6rem,4.6vw,2.6rem);font-weight:700;line-height:1.2;
margin:28px 0 8px;max-width:22em}
.lede span{color:var(--bar)}
.sub{color:var(--muted);margin:0 0 28px}
.grid{display:grid;gap:20px;grid-template-columns:1fr}
@media (min-width:820px){.grid{grid-template-columns:1.1fr .9fr}}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:20px}
h2{font-size:1rem;margin:0 0 14px;font-weight:700}
.stock{list-style:none;margin:0;padding:0;display:grid;gap:14px}
.row{display:grid;grid-template-columns:1fr auto;gap:4px 10px;align-items:baseline}
.name{font-weight:600}
.qty{color:var(--muted);font-variant-numeric:tabular-nums}
.track{grid-column:1/-1;position:relative;height:12px;background:var(--bar2);border-radius:6px}
.fill{position:absolute;inset:0 auto 0 0;background:var(--ok);border-radius:6px}
.fill.low{background:var(--low)}
.tick{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--ink)}
.chip{background:var(--low);color:var(--lowtext);border-radius:4px;padding:0 6px;
font-size:.8rem;font-weight:700;margin-left:8px}
.legend{color:var(--muted);font-size:.85rem;margin:14px 0 0}
.week{display:flex;align-items:flex-end;gap:10px;height:190px;padding-top:8px}
.day{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;
height:100%;gap:6px;min-width:0}
.bar{width:100%;background:var(--bar);border-radius:6px 6px 0 0;min-height:3px}
.bar.today{background:var(--low)}
.amt{font-size:.75rem;color:var(--muted);font-variant-numeric:tabular-nums}
.dow{font-size:.85rem;font-weight:600}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:9px 6px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;font-size:.85rem}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.table-wrap{overflow-x:auto}
.empty{color:var(--muted);margin:0}
footer{color:var(--muted);font-size:.85rem;margin-top:22px}
"""


def build_dashboard_html() -> tuple[str, dict]:
    today = date.today()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    with get_db() as db:
        inv = db.execute("SELECT * FROM inventory ORDER BY item").fetchall()
        daily = {
            r["sale_date"]: r["revenue"]
            for r in db.execute(
                "SELECT sale_date, SUM(total_kes) AS revenue FROM sales "
                "WHERE sale_date >= ? GROUP BY sale_date",
                (days[0].isoformat(),),
            ).fetchall()
        }
        top = db.execute(
            """SELECT item, SUM(quantity) AS units, SUM(total_kes) AS revenue
               FROM sales WHERE sale_date >= ? GROUP BY item
               ORDER BY revenue DESC LIMIT 5""",
            (days[0].isoformat(),),
        ).fetchall()

    today_total = daily.get(today.isoformat(), 0)
    week_total = sum(daily.values())
    low_count = sum(1 for r in inv if r["quantity"] <= r["reorder_level"])
    stock_value = sum(r["quantity"] * r["price_kes"] for r in inv)

    if low_count == 0:
        lede = f'KES <span>{today_total:,.0f}</span> taken today. Everything is above its reorder level.'
    else:
        noun = "item needs" if low_count == 1 else "items need"
        lede = (
            f'KES <span>{today_total:,.0f}</span> taken today. '
            f'{low_count} {noun} reordering.'
        )
    sub = f"KES {week_total:,.0f} sold in the last 7 days. Stock on the shelves is worth KES {stock_value:,.0f}."

    # Stock bars: sort low items first so the owner sees what to order.
    scale = max([r["quantity"] for r in inv] + [r["reorder_level"] * 1.3 for r in inv] + [1])
    stock_rows = []
    for r in sorted(inv, key=lambda r: (r["quantity"] > r["reorder_level"], r["item"])):
        is_low = r["quantity"] <= r["reorder_level"]
        fill = min(r["quantity"] / scale * 100, 100)
        tick = min(r["reorder_level"] / scale * 100, 100)
        chip = '<span class="chip">Reorder</span>' if is_low else ""
        stock_rows.append(
            f'<li class="row"><span class="name">{html.escape(r["item"])}{chip}</span>'
            f'<span class="qty">{r["quantity"]} left</span>'
            f'<div class="track" role="img" aria-label="{r["quantity"]} in stock, reorder at {r["reorder_level"]}">'
            f'<div class="fill{" low" if is_low else ""}" style="width:{fill:.1f}%"></div>'
            f'<div class="tick" style="left:{tick:.1f}%"></div></div></li>'
        )

    # Week chart
    peak = max(list(daily.values()) + [1])
    week_cols = []
    for d in days:
        value = daily.get(d.isoformat(), 0)
        height = max(value / peak * 150, 3) if value else 3
        cls = "bar today" if d == today else "bar"
        week_cols.append(
            f'<div class="day"><span class="amt">{value:,.0f}</span>'
            f'<div class="{cls}" style="height:{height:.0f}px"></div>'
            f'<span class="dow">{d.strftime("%a")}</span></div>'
        )

    if top:
        top_rows = "".join(
            f'<tr><td>{html.escape(r["item"])}</td><td class="n">{r["units"]}</td>'
            f'<td class="n">{r["revenue"]:,.0f}</td></tr>'
            for r in top
        )
        top_html = (
            '<div class="table-wrap"><table><thead><tr><th>Item</th>'
            '<th class="n">Units sold</th><th class="n">KES</th></tr></thead>'
            f"<tbody>{top_rows}</tbody></table></div>"
        )
    else:
        top_html = '<p class="empty">No sales yet. Record a sale and it will show up here.</p>'

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(SHOP_NAME)} dashboard</title>
<style>{DASHBOARD_CSS}</style></head>
<body>
<header><h1>{html.escape(SHOP_NAME)}</h1><p class="date">{today.strftime("%A %d %B %Y")}</p></header>
<p class="lede">{lede}</p>
<p class="sub">{sub}</p>
<div class="grid">
<section><h2>Stock on the shelf</h2>
<ul class="stock">{"".join(stock_rows)}</ul>
<p class="legend">The dark line marks the reorder level. Yellow bars are at or below it.</p></section>
<section><h2>Sales this week (KES)</h2><div class="week">{"".join(week_cols)}</div></section>
</div>
<section style="margin-top:20px"><h2>Best sellers this week</h2>{top_html}</section>
<footer>Updated {today.isoformat()}. Ask Claude to refresh the dashboard after new sales.</footer>
</body></html>"""
    stats = {
        "today": today_total,
        "week": week_total,
        "low": low_count,
        "value": stock_value,
    }
    return page, stats


@mcp.tool()
def generate_dashboard(open_browser: bool = True) -> str:
    """Build a dashboard page (today's takings, stock levels, weekly sales and
    best sellers) and open it in the browser. Run again after new sales to refresh."""
    page, stats = build_dashboard_html()
    DASHBOARD_PATH.write_text(page, encoding="utf-8")
    opened = ""
    if open_browser:
        try:
            webbrowser.open(DASHBOARD_PATH.as_uri())
            opened = " Opened in your browser."
        except Exception:
            opened = " Could not open the browser automatically."
    return (
        f"Dashboard saved to {DASHBOARD_PATH}.{opened}\n"
        f"Today: KES {stats['today']:,.0f}. Last 7 days: KES {stats['week']:,.0f}. "
        f"Items to reorder: {stats['low']}. Stock value: KES {stats['value']:,.0f}."
    )


# ---------- demo data ----------

DEMO_SALES = {
    6: [("bread", 14), ("maize flour 2kg", 6), ("milk 500ml", 10)],
    5: [("bread", 18), ("sugar 1kg", 4), ("tea leaves 250g", 3)],
    4: [("maize flour 2kg", 9), ("cooking oil 1L", 3), ("bread", 12), ("milk 500ml", 8)],
    3: [("bread", 20), ("rice 1kg", 5), ("sugar 1kg", 6)],
    2: [("milk 500ml", 14), ("maize flour 2kg", 8), ("cooking oil 1L", 4), ("tea leaves 250g", 5)],
    1: [("bread", 16), ("rice 1kg", 7), ("maize flour 2kg", 7), ("sugar 1kg", 3)],
    0: [("bread", 9), ("milk 500ml", 6), ("maize flour 2kg", 4)],
}

DEMO_SUPPLIERS = [
    ("Mama Njeri Wholesalers", "0700000001", "maize, sugar, rice, flour"),
    ("Kamau Dairy and Bakery", "0700000002", "milk, bread"),
    ("Tea and Oil Traders", "0700000003", "tea, oil"),
]


@mcp.tool()
def load_demo_data() -> str:
    """Fill the shop with a week of sample sales and three sample suppliers so
    the dashboard and WhatsApp tools have something to show. Only works while
    no sales have been recorded, so real records are never mixed with demo data.
    The sample supplier phone numbers are placeholders: use add_supplier to
    replace them with real ones."""
    with get_db() as db:
        if db.execute("SELECT COUNT(*) FROM sales").fetchone()[0] > 0:
            return "Sales already exist, so demo data was not loaded. Your real records are untouched."
        prices = {r["item"]: r["price_kes"] for r in db.execute("SELECT item, price_kes FROM inventory")}
        today = date.today()
        count = 0
        for days_ago, lines in DEMO_SALES.items():
            day = (today - timedelta(days=days_ago)).isoformat()
            for item, qty in lines:
                if item in prices:
                    db.execute(
                        "INSERT INTO sales (sale_date, item, quantity, total_kes) VALUES (?, ?, ?, ?)",
                        (day, item, qty, prices[item] * qty),
                    )
                    count += 1
        for name, phone, items in DEMO_SUPPLIERS:
            db.execute(
                "INSERT OR REPLACE INTO suppliers (name, phone, items) VALUES (?, ?, ?)",
                (name, clean_phone(phone), items),
            )
    return (
        f"Loaded {count} sample sales over 7 days and {len(DEMO_SUPPLIERS)} sample suppliers "
        "(placeholder phone numbers). Try generate_dashboard next."
    )


if __name__ == "__main__":
    init_db()
    mcp.run()  # stdio transport
