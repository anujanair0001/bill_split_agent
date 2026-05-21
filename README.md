# BillSplit Agent

**Context-aware restaurant bill splitting agent**

BillSplit Agent is a small Python project inspired by TripCraft AI's agent-style structure. It reads restaurant bill text, asks who ate, asks who shared each item, and returns a fair split across diners.

## What It Does

- Parses restaurant bill text into items, tax, and service charge.
- Reads receipt images or PDFs with OCR when local OCR dependencies are installed.
- Interactively asks for diner names and item assignments.
- Also supports simple assignment notes like `Alice had pasta, Bob had burger, everyone shared fries`.
- Splits shared items evenly across assigned people.
- Splits tax and service charge proportionally by each person's item subtotal.
- Stores lightweight in-memory session data such as recent people and split results.
- Runs without external AI dependencies, while keeping an agent/tool architecture that can be upgraded later.

## Quick Start

```powershell
cd bill_split_agent
pip install -r requirements.txt
streamlit run app.py
```

The UI lets you upload a receipt image/PDF, review OCR text, edit detected items, add people, assign dishes, and calculate the split.

## Streamlit + Supabase Persistence

For team use on Streamlit Community Cloud, configure Supabase so saved bills and receipt uploads survive app restarts.

Create this table in Supabase SQL editor:

```sql
create table if not exists saved_bills (
  id text primary key,
  restaurant_name text,
  payload jsonb not null,
  receipt_file_path text,
  receipt_file_name text,
  receipt_file_type text,
  created_at timestamptz,
  updated_at timestamptz
);

create table if not exists app_settings (
  key text primary key,
  value jsonb not null
);
```

Create a private Storage bucket named:

```text
receipts
```

Add these Streamlit secrets:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_KEY = "your-service-role-key"
SUPABASE_BILLS_TABLE = "saved_bills"
SUPABASE_SETTINGS_TABLE = "app_settings"
SUPABASE_RECEIPTS_BUCKET = "receipts"
```

If these secrets are missing, the app falls back to local `data/saved_bills.json` and `data/team_members.json`.

You can also use the command-line flow:

```powershell
python main.py
```

When prompted, paste the receipt text and type `END` on its own line. Then enter the names and choose who ate each detected item.

Run with a receipt text file:

```powershell
python main.py --bill-file receipt.txt
```

Run with a receipt image:

```powershell
python main.py --image-file receipt.jpg
```

OCR requires Tesseract OCR to be installed and available on your `PATH`. PDF OCR also requires Poppler. If OCR fails, the app falls back to manual receipt text paste.

Run the built-in demo:

```powershell
python main.py --demo
```

## Project Structure

```text
bill_split_agent/
  main.py                     Demo and CLI entry point
  requirements.txt            Minimal dependencies
  src/
    agents/                   Agent orchestration
    tools/                    Bill parsing, assignment, and split tools
    utils/                    Memory and formatting helpers
  tests/                      Unit tests
```

## Example

Input bill:

```text
Noodle House
Pasta 18.00
Burger 22.00
Fries 12.00
Service Charge 5.20
SST 3.12
Total 60.32
```

Assignment note:

```text
Alice had pasta; Bob had burger; everyone shared fries
```

Output:

```text
Alice pays 27.84
Bob pays 32.48
```
