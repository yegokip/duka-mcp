# Duka MCP Server

An MCP server that lets an AI assistant help run a small shop: check stock, record sales, flag low inventory, and summarize daily revenue (in KES). Built with the official MCP Python SDK.
 ![Demo](PAGE.png) 
## Tools

| Tool | What it does |
|------|--------------|
| `check_stock(item)` | Stock level and price (partial names work) |
| `low_stock_report()` | Items at or below their reorder level |
| `record_sale(item, quantity)` | Logs a sale and reduces stock |
| `get_daily_sales(day)` | Revenue summary per item for a day |
| `restock(item, quantity)` | Adds delivered units to stock |

## Setup

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install "mcp[cli]<2"
python server.py                  # creates duka.db with sample data on first run
```

## Connect to Claude Desktop

Open Settings > Developer > Edit Config and add:

```json
{
  "mcpServers": {
    "duka": {
      "command": "/full/path/to/venv/bin/python",
      "args": ["/full/path/to/server.py"]
    }
  }
}
```

Restart Claude Desktop, then try:

- "What's running low in the shop?"
- "I just sold 3 bags of maize flour 2kg."
- "How much did we make today?"
- "We got 20 more sugar 1kg from the supplier."

## Make it your own

Edit the seed data in `init_db()` to match a real shop's products and prices. Ideas for next steps: read from a Google Sheet instead of SQLite, add a tool that drafts WhatsApp replies to customers, or add M-Pesa payment tracking.
