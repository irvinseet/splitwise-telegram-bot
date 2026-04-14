import logging
import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from db import Database
from splitter import format_balances, parse_split, simplify_debts

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
db = Database("splitbot.db")

(
    ADD_DESC,
    ADD_AMOUNT,
    ADD_SPLIT_MODE,
    ADD_MEMBERS,
    ADD_SPLIT_VALUES,
    ADD_CONFIRM,
    IAM_PICK,
) = range(7)


def get_group_id(update: Update) -> int:
    return update.effective_chat.id


def get_user(update: Update) -> tuple[int, str]:
    u = update.effective_user
    name = u.username or u.first_name or str(u.id)
    return u.id, name


def is_group_chat(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type in {"group", "supergroup"}


async def track_telegram_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    uid, tg_name = get_user(update)
    db.upsert_telegram_user(uid, tg_name)


def split_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➗ Equal split", callback_data="mode_equal")],
        [InlineKeyboardButton("💰 Exact amounts", callback_data="mode_exact")],
        [InlineKeyboardButton("📊 Percentages", callback_data="mode_percent")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ])


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data="confirm_yes"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
        ]
    ])


def member_picker_keyboard(members: list[dict], prefix: str) -> InlineKeyboardMarkup:
    buttons = []
    for m in members:
        buttons.append([
            InlineKeyboardButton(
                m["display_name"],
                callback_data=f"{prefix}_{m['id']}",
            )
        ])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


def build_split_member_keyboard(members: list[dict], selected_ids: list[int]) -> InlineKeyboardMarkup:
    buttons = []
    for m in members:
        checked = m["id"] in selected_ids
        buttons.append([
            InlineKeyboardButton(
                f"{'✅' if checked else '☐'} {m['display_name']}",
                callback_data=f"member_{m['id']}",
            )
        ])
    buttons.append([InlineKeyboardButton("✅ Done selecting", callback_data="members_done")])
    buttons.append([InlineKeyboardButton("👥 All members", callback_data="members_all")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


async def require_group(update: Update) -> bool:
    if is_group_chat(update):
        return True
    if update.message:
        await update.message.reply_text("Use this command in a group chat.")
    elif update.callback_query:
        await update.callback_query.answer("Use this in a group chat.", show_alert=True)
    return False


def get_linked_member_or_none(group_id: int, telegram_user_id: int) -> dict | None:
    return db.get_member_by_telegram_user(group_id, telegram_user_id)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid, tg_name = get_user(update)
    db.upsert_telegram_user(uid, tg_name)

    await update.message.reply_text(
        "👋 I’m your group expense splitter.\n\n"
        "Use me in a group chat to track shared expenses.\n\n"

        "🧾 Core:\n"
        "  /add — add a new expense\n"
        "  /history — recent expenses\n"
        "  /myexpenses — your actual trip spend\n\n"

        "💰 Balances:\n"
        "  /balance — see all debts\n"
        "  /simplify — minimal payments needed\n\n"

        "👥 Members:\n"
        "  /addmember <name> — add a member\n"
        "  /iam — link yourself to your name\n"
        "  /members — list members\n\n"

        "💸 Settling up:\n"
        "  /settle <nickname> — clear what you owe this person\n\n"

        "🛠️ Manage:\n"
        "  /delete <id> — delete an expense you added\n"
        "  /help — show this message\n\n"

        "💡 Tip: If /add doesn’t work, run /iam first."
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await start(update, ctx)


async def addmember_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_group(update):
        return

    if not ctx.args:
        await update.message.reply_text("Usage: /addmember <display name>")
        return

    group_id = get_group_id(update)
    display_name = " ".join(ctx.args).strip()

    if not display_name:
        await update.message.reply_text("Display name cannot be empty.")
        return

    try:
        member_id = db.add_member(group_id, display_name)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.reply_text(f"✅ Added member #{member_id}: {display_name}")


async def members_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_group(update):
        return

    group_id = get_group_id(update)
    members = db.get_members(group_id)

    if not members:
        await update.message.reply_text("No members yet. Use /addmember <name> first.")
        return

    lines = []
    for m in members:
        linked = " ✅ linked" if m["telegram_user_id"] else ""
        lines.append(f"• #{m['id']} {m['display_name']}{linked}")

    await update.message.reply_text("👥 Group members:\n" + "\n".join(lines))


async def iam_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_group(update):
        return

    telegram_user_id, tg_name = get_user(update)
    db.upsert_telegram_user(telegram_user_id, tg_name)
    group_id = get_group_id(update)

    linked = db.get_member_by_telegram_user(group_id, telegram_user_id)
    if linked:
        await update.message.reply_text(
            f"You're already linked to #{linked['id']} {linked['display_name']}."
        )
        return

    members = db.get_members(group_id)
    if not members:
        await update.message.reply_text(
            "No member profiles exist yet. Use /addmember <name> first."
        )
        return

    ctx.user_data["iam_group_id"] = group_id
    await update.message.reply_text(
        "Who are you in this group?",
        reply_markup=member_picker_keyboard(members, "iam"),
    )
    return IAM_PICK


async def iam_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        ctx.user_data.pop("iam_group_id", None)
        return ConversationHandler.END

    if not query.data.startswith("iam_"):
        return IAM_PICK

    member_id = int(query.data.split("_", 1)[1])
    group_id = ctx.user_data["iam_group_id"]
    telegram_user_id, tg_name = get_user(update)

    try:
        db.link_member_to_telegram_user(group_id, member_id, telegram_user_id, tg_name)
    except ValueError as e:
        await query.edit_message_text(str(e))
        return ConversationHandler.END

    member = db.get_member(group_id, member_id)
    await query.edit_message_text(
        f"✅ Linked you to #{member['id']} {member['display_name']}."
    )
    ctx.user_data.pop("iam_group_id", None)
    return ConversationHandler.END


async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_group(update):
        return ConversationHandler.END

    telegram_user_id, tg_name = get_user(update)
    db.upsert_telegram_user(telegram_user_id, tg_name)

    group_id = get_group_id(update)
    payer = db.get_member_by_telegram_user(group_id, telegram_user_id)

    if not payer:
        members = db.get_members(group_id)
        if not members:
            await update.message.reply_text(
                "No member profiles yet. Use /addmember <name> first."
            )
            return ConversationHandler.END

        await update.message.reply_text(
            "You're not linked to a member profile yet. Use /iam first."
        )
        return ConversationHandler.END

    ctx.user_data.clear()
    ctx.user_data["group_id"] = group_id
    ctx.user_data["payer_member_id"] = payer["id"]
    ctx.user_data["payer_name"] = payer["display_name"]

    await update.message.reply_text(
        "📝 What's the expense? (e.g. *Dinner*, *Taxi*, *Groceries*)",
        parse_mode="Markdown",
    )
    return ADD_DESC


async def add_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["desc"] = update.message.text.strip()
    await update.message.reply_text("💵 How much? (e.g. *45.50*)", parse_mode="Markdown")
    return ADD_AMOUNT


async def add_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a valid positive number.")
        return ADD_AMOUNT

    ctx.user_data["amount"] = amount
    await update.message.reply_text(
        "How do you want to split this?",
        reply_markup=split_mode_keyboard(),
    )
    return ADD_SPLIT_MODE


async def add_split_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        ctx.user_data.clear()
        await query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

    mode_map = {
        "mode_equal": "equal",
        "mode_exact": "exact",
        "mode_percent": "percent",
    }
    ctx.user_data["mode"] = mode_map[query.data]

    group_id = ctx.user_data["group_id"]
    members = db.get_members(group_id)

    if not members:
        await query.edit_message_text("No members found. Use /addmember first.")
        return ConversationHandler.END

    ctx.user_data["selected_member_ids"] = []
    ctx.user_data["members_list"] = members

    await query.edit_message_text(
        "👥 Who's splitting this? Select members then tap *Done*.",
        reply_markup=build_split_member_keyboard(members, []),
        parse_mode="Markdown",
    )
    return ADD_MEMBERS


async def add_members(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel":
        ctx.user_data.clear()
        await query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

    members = ctx.user_data["members_list"]
    selected_ids = ctx.user_data.get("selected_member_ids", [])

    if data == "members_all":
        selected_ids = [m["id"] for m in members]
        ctx.user_data["selected_member_ids"] = selected_ids

    elif data.startswith("member_"):
        member_id = int(data.split("_", 1)[1])
        if member_id in selected_ids:
            selected_ids.remove(member_id)
        else:
            selected_ids.append(member_id)
        ctx.user_data["selected_member_ids"] = selected_ids

    elif data == "members_done":
        if not selected_ids:
            await query.answer("Select at least one member.", show_alert=True)
            return ADD_MEMBERS

        mode = ctx.user_data["mode"]
        if mode == "equal":
            return await _finalize_split(query, ctx, {mid: None for mid in selected_ids})

        member_map = {m["id"]: m["display_name"] for m in members}
        ordered_names = "\n".join(f"• {member_map[mid]}" for mid in selected_ids)

        if mode == "exact":
            await query.edit_message_text(
                f"💰 Enter exact amounts in this order:\n{ordered_names}\n\n"
                "Send as space-separated numbers (e.g. *10 20 15.50*)",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text(
                f"📊 Enter percentages in this order:\n{ordered_names}\n\n"
                "Send as space-separated numbers that sum to 100 (e.g. *50 30 20*)",
                parse_mode="Markdown",
            )
        return ADD_SPLIT_VALUES

    await query.edit_message_text(
        "👥 Who's splitting this? Select members then tap *Done*.",
        reply_markup=build_split_member_keyboard(members, selected_ids),
        parse_mode="Markdown",
    )
    return ADD_MEMBERS


async def add_split_values(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    selected_ids = ctx.user_data["selected_member_ids"]
    mode = ctx.user_data["mode"]
    amount = ctx.user_data["amount"]

    try:
        values = [float(v.replace(",", ".")) for v in text.split()]
        if len(values) != len(selected_ids):
            raise ValueError(f"expected {len(selected_ids)} values, got {len(values)}")

        if mode == "percent":
            total = sum(values)
            if abs(total - 100) > 0.01:
                await update.message.reply_text(
                    f"⚠️ Percentages must sum to 100 (got {total:.2f}). Try again."
                )
                return ADD_SPLIT_VALUES

        elif mode == "exact":
            total = sum(values)
            if abs(total - amount) > 0.01:
                await update.message.reply_text(
                    f"⚠️ Amounts must sum to {amount:.2f} (got {total:.2f}). Try again."
                )
                return ADD_SPLIT_VALUES

    except ValueError as e:
        await update.message.reply_text(f"⚠️ Invalid input: {e}. Try again.")
        return ADD_SPLIT_VALUES

    split_map = {mid: v for mid, v in zip(selected_ids, values)}
    return await _finalize_split(update, ctx, split_map)


async def _finalize_split(trigger, ctx: ContextTypes.DEFAULT_TYPE, split_map: dict[int, float | None]):
    mode = ctx.user_data["mode"]
    amount = ctx.user_data["amount"]
    desc = ctx.user_data["desc"]
    payer_name = ctx.user_data["payer_name"]
    members = ctx.user_data["members_list"]
    member_names = {m["id"]: m["display_name"] for m in members}

    splits = parse_split(mode, amount, split_map)
    ctx.user_data["splits"] = splits

    lines = [f"• {member_names.get(mid, str(mid))}: ${share:.2f}" for mid, share in splits.items()]
    summary = "\n".join(lines)

    msg = (
        f"📋 *Confirm expense*\n\n"
        f"📝 {desc}\n"
        f"💵 Total: ${amount:.2f}\n"
        f"👤 Paid by: {payer_name}\n\n"
        f"Split ({mode}):\n{summary}"
    )

    if hasattr(trigger, "edit_message_text"):
        await trigger.edit_message_text(msg, reply_markup=confirm_keyboard(), parse_mode="Markdown")
    else:
        await trigger.message.reply_text(msg, reply_markup=confirm_keyboard(), parse_mode="Markdown")

    return ADD_CONFIRM


async def add_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        ctx.user_data.clear()
        await query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

    group_id = ctx.user_data["group_id"]
    payer_member_id = ctx.user_data["payer_member_id"]
    payer_name = ctx.user_data["payer_name"]
    amount = ctx.user_data["amount"]
    desc = ctx.user_data["desc"]
    splits = ctx.user_data["splits"]

    expense_id = db.add_expense(
        group_id=group_id,
        payer_member_id=payer_member_id,
        payer_name=payer_name,
        amount=amount,
        desc=desc,
        splits=splits,
    )

    ctx.user_data.clear()

    await query.edit_message_text(
        f"✅ Expense #{expense_id} *{desc}* (${amount:.2f}) recorded!\n"
        f"Use /balance to see current balances.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


async def balance_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_group(update):
        return

    group_id = get_group_id(update)
    debts = db.get_balances(group_id)
    members = {m["id"]: m["display_name"] for m in db.get_members(group_id)}
    await update.message.reply_text(format_balances(debts, members), parse_mode="Markdown")


async def simplify_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_group(update):
        return

    group_id = get_group_id(update)
    debts = db.get_balances(group_id)
    members = {m["id"]: m["display_name"] for m in db.get_members(group_id)}
    simplified = simplify_debts(debts, members)

    if not simplified:
        await update.message.reply_text("🎉 All settled up!")
        return

    lines = [f"• {payer} → {receiver}: *${amount:.2f}*" for payer, receiver, amount in simplified]
    await update.message.reply_text(
        "💡 *Simplified debts:*\n\n" + "\n".join(lines),
        parse_mode="Markdown",
    )


async def history_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_group(update):
        return

    group_id = get_group_id(update)
    expenses = db.get_expenses(group_id, limit=10)

    if not expenses:
        await update.message.reply_text("No expenses yet. Use /add to get started.")
        return

    lines = []
    for e in expenses:
        lines.append(
            f"• #{e['id']} *{e['desc']}* — ${e['amount']:.2f} "
            f"(paid by {e['payer_name']}) [{e['created_at'][:10]}]"
        )

    await update.message.reply_text(
        "📜 *Recent expenses:*\n\n" + "\n".join(lines),
        parse_mode="Markdown",
    )


async def delete_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_group(update):
        return

    telegram_user_id, tg_name = get_user(update)
    db.upsert_telegram_user(telegram_user_id, tg_name)

    group_id = get_group_id(update)
    requester = db.get_member_by_telegram_user(group_id, telegram_user_id)

    if not requester:
        await update.message.reply_text("Use /iam first so I know which member you are.")
        return

    if not ctx.args:
        await update.message.reply_text("Usage: /delete <expense_id>")
        return

    try:
        expense_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Expense ID must be a number.")
        return

    deleted = db.delete_expense(group_id, expense_id, requester_member_id=requester["id"])
    if not deleted:
        await update.message.reply_text(
            "Could not delete it. Check the ID, or only the payer can delete it."
        )
        return

    await update.message.reply_text(f"🗑️ Deleted expense #{expense_id}.")


# async def undo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
#     if not await require_group(update):
#         return

#     telegram_user_id, tg_name = get_user(update)
#     db.upsert_telegram_user(telegram_user_id, tg_name)

#     group_id = get_group_id(update)
#     requester = db.get_member_by_telegram_user(group_id, telegram_user_id)

#     if not requester:
#         await update.message.reply_text("Use /iam first so I know which member you are.")
#         return

#     expense = db.delete_latest_expense_by_payer(group_id, requester["id"])
#     if not expense:
#         await update.message.reply_text("No recent expense of yours found to undo.")
#         return

#     await update.message.reply_text(
#         f"↩️ Undid expense #{expense['id']} *{expense['desc']}* (${expense['amount']:.2f}).",
#         parse_mode="Markdown",
#     )


async def settle_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_group(update):
        return

    telegram_user_id, tg_name = get_user(update)
    db.upsert_telegram_user(telegram_user_id, tg_name)

    group_id = get_group_id(update)
    requester = db.get_member_by_telegram_user(group_id, telegram_user_id)

    if not requester:
        await update.message.reply_text("Use /iam first so I know which member you are.")
        return

    if not ctx.args:
        await update.message.reply_text("Usage: /settle <nickname>")
        return

    target_name = " ".join(ctx.args).strip()
    target = db.get_member_by_name(group_id, target_name)

    if not target:
        await update.message.reply_text(f"Member '{target_name}' not found in this group.")
        return

    if target["id"] == requester["id"]:
        await update.message.reply_text("You can't settle with yourself.")
        return

    settled = db.settle_between(group_id, requester["id"], target["id"])
    await update.message.reply_text(
        f"✅ Cleared what you owe {target['display_name']}. (${settled:.2f} cleared)"
    )


async def settlemember_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_group(update):
        return

    telegram_user_id, tg_name = get_user(update)
    db.upsert_telegram_user(telegram_user_id, tg_name)

    group_id = get_group_id(update)
    requester = db.get_member_by_telegram_user(group_id, telegram_user_id)

    if not requester:
        await update.message.reply_text("Use /iam first so I know which member you are.")
        return

    if not ctx.args:
        await update.message.reply_text("Usage: /settlemember <member_id>")
        return

    try:
        target_member_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Member ID must be a number.")
        return

    target = db.get_member(group_id, target_member_id)
    if not target:
        await update.message.reply_text("Member not found in this group.")
        return

    settled = db.settle_between(group_id, requester["id"], target_member_id)
    await update.message.reply_text(
        f"✅ Settled debts between {requester['display_name']} and {target['display_name']}. "
        f"(${settled:.2f} cleared)"
    )

async def myexpenses_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await require_group(update):
        return

    telegram_user_id, tg_name = get_user(update)
    db.upsert_telegram_user(telegram_user_id, tg_name)

    group_id = get_group_id(update)
    member = db.get_member_by_telegram_user(group_id, telegram_user_id)

    if not member:
        await update.message.reply_text("Use /iam first.")
        return

    member_id = member["id"]

    # 1. total paid
    expenses = db.get_expenses_by_payer(group_id, member_id)
    total_paid = sum(e["amount"] for e in expenses)

    # 2. compute debts
    debts = db.get_balances(group_id)

    owed_to_me = 0
    i_owe = 0

    for (debtor, creditor), amount in debts.items():
        if debtor == member_id:
            i_owe += amount
        elif creditor == member_id:
            owed_to_me += amount

    # 3. net spend
    net_spend = total_paid - owed_to_me + i_owe

    await update.message.reply_text(
        f"🧾 *Your trip summary:*\n\n"
        f"Paid: *${total_paid:.2f}*\n"
        f"Others owe you: *${owed_to_me:.2f}*\n"
        f"You owe others: *${i_owe:.2f}*\n\n"
        f"👉 *Net spend: ${net_spend:.2f}*",
        parse_mode="Markdown"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE, add_desc)],
            ADD_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE, add_amount)],
            ADD_SPLIT_MODE: [CallbackQueryHandler(add_split_mode)],
            ADD_MEMBERS: [CallbackQueryHandler(add_members)],
            ADD_SPLIT_VALUES: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE, add_split_values)],
            ADD_CONFIRM: [CallbackQueryHandler(add_confirm)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    iam_conv = ConversationHandler(
        entry_points=[CommandHandler("iam", iam_cmd)],
        states={
            IAM_PICK: [CallbackQueryHandler(iam_pick)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    app.add_handler(
        MessageHandler(filters.TEXT & filters.UpdateType.MESSAGE, track_telegram_user),
        group=-1,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("addmember", addmember_cmd))
    app.add_handler(CommandHandler("members", members_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("simplify", simplify_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("settle", settle_cmd))
    app.add_handler(CommandHandler("myexpenses", myexpenses_cmd))
    app.add_handler(iam_conv)
    app.add_handler(add_conv)

    logger.info("Bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
