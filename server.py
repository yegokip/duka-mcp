"""
Duka MCP Server: an AI assistant for a small shop.

Lets an AI app (Claude Desktop, etc.) check stock, record sales, flag items
running low, and summarize daily sales, using plain conversation.

Data lives in a local SQLite file (duka.db), created and seeded on first run.

Setup:
    pip install "mcp[cli]<2"
    python server.py          # runs over stdio, which is what Claude Desktop uses
"""

import sqlite3
from datetime import date
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DB_PATH = Path(__file__).parent / "duka.db"

mcp = FastMCP("duka-shop-assistant")


# ---------- database helpers ----------

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables and seed sample Nairobi shop data on first run."""
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


# ---------- tools ----------

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
            "SELECT * FROM inventory WHERE item = ?", (item.lower(),)
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
        rows = db.execute(
            """SELECT item, SUM(quantity) AS units, SUM(total_kes) AS revenue
               FROM sales WHERE sale_date = ? GROUP BY item ORDER BY revenue DESC""",
            (day,),
        ).fetchall()
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
        cur = db.execute(
            "UPDATE inventory SET quantity = quantity + ? WHERE item = ?",
            (quantity, item.lower()),
        )
        if cur.rowcount == 0:
            return f"'{item}' not found. Use check_stock to find the exact name."
        new_qty = db.execute(
            "SELECT quantity FROM inventory WHERE item = ?", (item.lower(),)
        ).fetchone()[0]
    return f"Restocked {item}: now {new_qty} units."


if __name__ == "__main__":
    init_db()
    mcp.run()  # stdio transport
