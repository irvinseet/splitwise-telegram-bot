
# Telegram Expense Splitting Bot

A self-contained Telegram bot for splitting expenses in group chats.

All data stored locally in SQLite.

---

## ✨ Features

* Equal / Exact / Percentage splits
* Custom member profiles (supports silent members)
* Nickname-based identity (`/iam`)
* Automatic debt simplification (min cash flow)
* Settle by nickname (based on simplified balances)
* Personal trip spend view (`/myexpenses`)
* Item-level breakdown (`/myexpenses full`)
* Expense history
* Multi-group support (data isolated per group)

---

## 🚀 Setup

### 1. Create a Telegram bot

1. Message @BotFather on Telegram
2. Send `/newbot`
3. Copy your bot token

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set bot token

```bash
export BOT_TOKEN="your-token-here"
```

### 4. Run

```bash
python bot.py
```

---

## 📌 Core Concepts

### Members

Members are **group-defined profiles**, not strictly tied to Telegram usernames.

---

### Identity

Link yourself to a member:

```text
/iam
```

---

### Expenses vs Balances

* `/myexpenses` → your **actual trip spend**
* `/balance` → **simplified debts (who should pay who)**
* `/simplify` → same as `/balance` (minimal payments)

---

### Settlements

Settlements are applied against **simplified balances**, not raw expenses.

This ensures:

* no incorrect pairwise clearing
* correct net settlement across the group

---

## 🧾 Commands

### Expenses

* `/add` — add a new expense
* `/history` — recent expenses
* `/myexpenses` — your trip summary
* `/myexpenses full` — include item-level breakdown

---

### Balances

* `/balance` — simplified debts (recommended view)
* `/simplify` — same as `/balance`

---

### Members

* `/addmember <name>` — create member
* `/iam` — link yourself
* `/members` — list members

---

### Settling

* `/settle <nickname>` — settle what you owe this person

---

### Manage

* `/delete <id>` — delete an expense you added
* `/cancel` — cancel current flow
* `/help` — show help

---

## 📊 How `/myexpenses` Works

Unlike balances, this reflects **actual consumption**, not current debt state.

Shows:

* **Paid upfront** — how much you covered
* **Your share** — what you actually consumed
* **Net transfer** — what others should pay you / you should pay

Example:

```text
Paid upfront: $69
Your share: $23

👉 Others should pay you back: $46
```

---

## 📦 File Structure

```
splitbot/
├── bot.py
├── db.py
├── splitter.py
├── requirements.txt
└── splitbot.db
```

---

## ⚠️ Notes

* Balances are always computed from:

  * expenses
  * minus settlements
* No mutation of original expense data
* Floating-point rounding handled with tolerance (`0.005`)
* Data is local (SQLite), no external APIs

---

## 💡 Future Ideas

* Per-item debt breakdown (who owes you per expense)
* Partial settlements
* Export to CSV
* Web dashboard

