# Telegram Expense Splitting Bot

A self-contained Telegram bot for splitting expenses in group chats.

No Splitwise or external services required — all data stored locally in SQLite.

---

## ✨ Features

- Equal / Exact / Percentage splits
- Custom member profiles (supports silent members)
- Nickname-based identity (`/iam`)
- Debt simplification (min-cash-flow)
- Settle by nickname
- Personal trip spend view (`/myexpenses`)
- Expense history
- Multi-group support (data isolated per group)

---

## 🚀 Setup

### 1. Create a Telegram bot
1. Message @BotFather on Telegram
2. Send `/newbot`
3. Copy your bot token

### 2. Install dependencies
pip install -r requirements.txt

### 3. Set bot token
export BOT_TOKEN="your-token-here"

### 4. Run
python bot.py

---

## 📌 Core Concepts

### Members
Members are group-defined profiles (not tied strictly to Telegram usernames).
Supports nicknames and silent members.

### Identity
Link yourself:
`/iam`

### Expenses vs Balances
- `/myexpenses` → your actual trip cost
- `/balance` → full ledger
- `/simplify` → minimal payments

---

## 🧾 Commands

### Expenses
- /add — add a new expense
- /history — recent expenses
- /myexpenses — your net trip spend

### Balances
- /balance — who owes who
- /simplify — minimal payments

### Members
- /addmember <name>
- /iam
- /members

### Settling
- /settle <nickname>

### Manage
- /delete <id>
- /cancel
- /help

---



## 📂 File Structure

```
splitbot/
├── bot.py
├── db.py
├── splitter.py
├── requirements.txt
└── splitbot.db
```


