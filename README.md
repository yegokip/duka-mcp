 ![Demo]([(https://github.com/yegokip/duka-mcp/blob/main/secreen.jpeg))
# Duka MCP Server

An MCP server that lets an AI assistant run a small shop in plain conversation: track stock and sales, send supplier orders on WhatsApp, and show a live dashboard. Built with the official MCP Python SDK. Prices are in KES.

## Tools

| Tool | What it does |
|------|--------------|
| `check_stock(item)` | Stock level and price (partial names work) |
| `low_stock_report()` | Items at or below their reorder level |
| `record_sale(item, quantity)` | Logs a sale and reduces stock |
| `get_daily_sales(day)` | Revenue summary per item for a day |
| `restock(item, quantity)` | Adds delivered units to stock |
| `add_supplier(name, phone, items)` | Saves a supplier and the products they supply |
| `whatsapp_restock_messages()` | Writes an order for every low-stock item, grouped by supplier, with a link that opens WhatsApp with the message ready |
| `whatsapp_daily_report(phone)` | Today's sales report as a WhatsApp message |
| `generate_dashboard()` | Builds `dashboard.html`: takings today, stock levels, weekly sales, best sellers |
| `load_demo_data()` | Loads a week of sample sales and sample suppliers (only if no sales exist) |

### About the WhatsApp tools

They create click-to-chat links (`wa.me`). The owner taps the link, WhatsApp opens with the message already typed, and they press send. Nothing is sent automatically and no WhatsApp Business API key is needed. The sample supplier numbers are placeholders, so use `add_supplier` with real numbers (Kenyan formats like `0712345678` or `+254712345678` both work).

## Setup

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
python -m pip install --upgrade pip
pip install "mcp[cli]<2"
python server.py                  # creates duka.db with sample stock on first run
```

## Connect to Claude Desktop

Open Settings > Developer > Edit Config and add `mcpServers` at the top level of the file (not inside `preferences`):

```json
{
  "mcpServers": {
    "duka": {
      "command": "/full/path/to/venv/bin/python",
      "args": ["/full/path/to/server.py"],
      "env": { "DUKA_SHOP_NAME": "Mama Njeri Shop" }
    }
  }
}
```

`env` is optional and sets the shop name used on WhatsApp messages and the dashboard. Quit Claude Desktop fully (Cmd+Q) and reopen it.

## Demo script

1. "Load the demo data."
2. "What's running low in the shop?"
3. "Write the WhatsApp orders for my suppliers."
4. "I just sold 3 maize flour 2kg."
5. "Show me the dashboard."
6. "Send today's report to 0712345678 on WhatsApp."

## Make it your own

Edit the seed stock in `init_db()` to match a real shop. Ideas for next steps: read stock from a Google Sheet, record M-Pesa payments, or add customer credit (madeni) tracking.
