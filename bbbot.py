# Telegram Voucher Selling Bot - Pydroid
# Final version: HTML formatting is used only for copy-friendly UPI/voucher text.
# Install in Pydroid:
# pip install python-telegram-bot

import logging
import sqlite3
import threading
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# CONFIGURATION
# ============================================================
BOT_TOKEN = "8565228725:AAFARpW3oc6YBR_VnCiajB-Pdgn2iTXreEQ"
ADMIN_ID = 8726424011
UPI_ID = "relaxsubham@fam"

DB_FILE = "voucher_bot.db"

DEFAULT_PRODUCT_NAME = "BB ₹150 OFF on ₹300"
DEFAULT_PRICE = 20

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

db_lock = threading.RLock()


# ============================================================
# DATABASE
# ============================================================
def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with db_lock:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS vouchers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'available',
                created_at TEXT NOT NULL,
                sold_at TEXT,
                order_id TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                username TEXT,
                utr TEXT,
                amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                voucher_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        defaults = {
            "product_name": DEFAULT_PRODUCT_NAME,
            "price": str(DEFAULT_PRICE),
            "upi_id": UPI_ID,
            "terms": "Please use the voucher according to the issuer's rules and validity.",
            "sales_enabled": "1",
        }

        for key, value in defaults.items():
            cur.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                (key, value),
            )

        conn.commit()
        conn.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_setting(key):
    with db_lock:
        conn = get_db()
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?",
            (key,),
        ).fetchone()
        conn.close()
        return row["value"] if row else ""


def set_setting(key, value):
    with db_lock:
        conn = get_db()
        conn.execute("""
            INSERT INTO settings(key, value)
            VALUES(?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value
        """, (key, str(value)))
        conn.commit()
        conn.close()


def save_user(user):
    if not user:
        return

    with db_lock:
        conn = get_db()
        t = now()

        conn.execute("""
            INSERT INTO users(
                user_id, username, first_name, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                updated_at=excluded.updated_at
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            t,
            t,
        ))

        conn.commit()
        conn.close()


def available_stock():
    with db_lock:
        conn = get_db()
        row = conn.execute("""
            SELECT COUNT(*) AS n
            FROM vouchers
            WHERE status='available'
        """).fetchone()
        conn.close()
        return int(row["n"])


def generate_order_id(conn):
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM orders"
    ).fetchone()

    return (
        "ORD"
        + datetime.now().strftime("%Y%m%d%H%M%S")
        + f"{int(row['n']) + 1:04d}"
    )


# ============================================================
# KEYBOARDS
# ============================================================
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🛒 Buy Voucher",
            callback_data="buy"
        )],
        [InlineKeyboardButton(
            "📜 My Orders",
            callback_data="my_orders"
        )],
    ])


def payment_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📋 Copy UPI ID",
            callback_data="copy_upi"
        )],
        [InlineKeyboardButton(
            "💳 I Have Paid",
            callback_data="paid"
        )],
    ])


def voucher_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📋 Copy Voucher Code",
            callback_data="copy_last_voucher"
        )],
    ])


def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ Add Vouchers",
                callback_data="admin_add"
            ),
            InlineKeyboardButton(
                "📦 Stock",
                callback_data="admin_stock"
            ),
        ],
        [
            InlineKeyboardButton(
                "💰 Change Price",
                callback_data="admin_price"
            ),
            InlineKeyboardButton(
                "✏️ Change Name",
                callback_data="admin_name"
            ),
        ],
        [
            InlineKeyboardButton(
                "📜 Change T&C",
                callback_data="admin_terms"
            ),
            InlineKeyboardButton(
                "💳 Change UPI",
                callback_data="admin_upi"
            ),
        ],
        [
            InlineKeyboardButton(
                "🟢 Sales ON/OFF",
                callback_data="admin_sales"
            ),
            InlineKeyboardButton(
                "🧾 Pending",
                callback_data="admin_pending"
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 Statistics",
                callback_data="admin_stats"
            ),
            InlineKeyboardButton(
                "📋 Recent Orders",
                callback_data="admin_recent"
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 Broadcast",
                callback_data="admin_broadcast"
            ),
        ],
    ])


# ============================================================
# PRODUCT DISPLAY
# ============================================================
def product_text():
    name = get_setting("product_name")
    price = get_setting("price")
    stock = available_stock()
    sales = get_setting("sales_enabled") == "1"

    text = (
        "🎟️ " + name + "\n\n"
        "📦 Stock: " + str(stock) + "\n"
        "💰 Price: ₹" + price + "\n\n"
    )

    if not sales:
        text += "🔴 Sales are currently unavailable."
    elif stock <= 0:
        text += "❌ Out of Stock"
    else:
        text += "🛒 Tap Buy Voucher to continue."

    return text


# ============================================================
# USER COMMANDS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    context.user_data.clear()

    # IMPORTANT:
    # /start does NOT start payment or ask for UTR.
    await update.message.reply_text(
        "Welcome!\n\n" + product_text(),
        reply_markup=main_keyboard(),
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("You are not authorized.")
        return

    context.user_data.clear()

    await update.message.reply_text(
        "⚙️ Admin Panel\n\nChoose an option:",
        reply_markup=admin_keyboard(),
    )


# ============================================================
# CALLBACKS
# ============================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    save_user(user)
    data = query.data

    # --------------------------------------------------------
    # USER: BUY
    # --------------------------------------------------------
    if data == "buy":
        if get_setting("sales_enabled") != "1":
            await query.message.reply_text(
                "🔴 Sales are currently unavailable."
            )
            return

        if available_stock() <= 0:
            await query.message.reply_text("❌ Out of Stock")
            return

        name = get_setting("product_name")
        price = get_setting("price")
        upi = get_setting("upi_id")

        context.user_data["state"] = "payment_waiting"

        # HTML <code> makes the UPI ID selectable/copy-friendly
        # in Telegram clients.
        payment_text = (
            "🛒 Purchase\n\n"
            "🎟️ " + name + "\n"
            "💰 Price: ₹" + price + "\n\n"
            "💳 UPI ID:\n"
            "<code>" + upi.replace("&", "&amp;").replace(
                "<", "&lt;"
            ).replace(">", "&gt;") + "</code>\n\n"
            "Make the payment using the UPI ID above.\n"
            "Then tap I Have Paid."
        )

        await query.message.reply_text(
            payment_text,
            parse_mode=ParseMode.HTML,
            reply_markup=payment_keyboard(),
        )
        return

    # --------------------------------------------------------
    # USER: COPY UPI
    # --------------------------------------------------------
    if data == "copy_upi":
        upi = get_setting("upi_id")

        await query.message.reply_text(
            "📋 UPI ID\n\n"
            "<code>" + upi.replace("&", "&amp;").replace(
                "<", "&lt;"
            ).replace(">", "&gt;") + "</code>\n\n"
            "Tap/hold the UPI ID to copy it.",
            parse_mode=ParseMode.HTML,
        )
        return

    # --------------------------------------------------------
    # USER: I HAVE PAID
    # --------------------------------------------------------
    if data == "paid":
        if get_setting("sales_enabled") != "1":
            context.user_data.pop("state", None)
            await query.message.reply_text(
                "🔴 Sales are currently unavailable."
            )
            return

        if available_stock() <= 0:
            context.user_data.pop("state", None)
            await query.message.reply_text(
                "❌ Out of Stock"
            )
            return

        context.user_data["state"] = "waiting_utr"

        await query.message.reply_text(
            "Send your UTR / transaction ID now."
        )
        return

    # --------------------------------------------------------
    # USER: MY ORDERS
    # --------------------------------------------------------
    if data == "my_orders":
        with db_lock:
            conn = get_db()
            rows = conn.execute("""
                SELECT order_id, amount, status,
                       voucher_code, created_at
                FROM orders
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT 10
            """, (user.id,)).fetchall()
            conn.close()

        if not rows:
            await query.message.reply_text(
                "📜 You have no orders yet."
            )
            return

        for row in rows:
            text = (
                "📜 Order\n\n"
                "Order ID: " + row["order_id"] + "\n"
                "Amount: ₹" + str(row["amount"]) + "\n"
                "Status: " + row["status"] + "\n"
                "Date: " + row["created_at"]
            )

            if row["voucher_code"]:
                text += (
                    "\n\n🎁 Voucher Code:\n"
                    "<code>" +
                    row["voucher_code"].replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;") +
                    "</code>"
                )

            await query.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
            )
        return

    # --------------------------------------------------------
    # USER: COPY LAST VOUCHER
    # --------------------------------------------------------
    if data == "copy_last_voucher":
        with db_lock:
            conn = get_db()
            row = conn.execute("""
                SELECT voucher_code
                FROM orders
                WHERE user_id=?
                  AND status='approved'
                  AND voucher_code IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
            """, (user.id,)).fetchone()
            conn.close()

        if not row:
            await query.message.reply_text(
                "No delivered voucher found."
            )
            return

        code = row["voucher_code"]

        await query.message.reply_text(
            "📋 Voucher Code\n\n"
            "<code>" +
            code.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;") +
            "</code>\n\n"
            "Tap/hold the code to copy it.",
            parse_mode=ParseMode.HTML,
        )
        return

    # --------------------------------------------------------
    # ADMIN ONLY BELOW
    # --------------------------------------------------------
    if user.id != ADMIN_ID:
        await query.message.reply_text(
            "You are not authorized."
        )
        return

    if data == "admin_broadcast":
        context.user_data["state"] = "admin_broadcast"
        await query.message.reply_text(
            "📢 Broadcast Mode\n\n"
            "Send the message you want to broadcast to all registered users.\n\n"
            "The bot will send it as plain text."
        )
        return

    if data == "admin_add":
        context.user_data["state"] = "admin_add_vouchers"

        await query.message.reply_text(
            "Send voucher codes now, one code per line.\n\n"
            "Example:\n"
            "CODE001\n"
            "CODE002\n"
            "CODE003"
        )
        return

    if data == "admin_stock":
        await query.message.reply_text(
            "📦 Current Stock: " + str(available_stock())
        )
        return

    if data == "admin_price":
        context.user_data["state"] = "admin_price"

        await query.message.reply_text(
            "Send the new price in rupees.\n"
            "Example: 25"
        )
        return

    if data == "admin_name":
        context.user_data["state"] = "admin_name"

        await query.message.reply_text(
            "Send the new voucher name."
        )
        return

    if data == "admin_terms":
        context.user_data["state"] = "admin_terms"

        await query.message.reply_text(
            "Send the new Terms & Conditions."
        )
        return

    if data == "admin_upi":
        context.user_data["state"] = "admin_upi"

        await query.message.reply_text(
            "Send the new UPI ID."
        )
        return

    if data == "admin_sales":
        current = get_setting("sales_enabled")
        new = "0" if current == "1" else "1"

        set_setting("sales_enabled", new)

        status = "enabled" if new == "1" else "disabled"

        await query.message.reply_text(
            "Sales are now " + status + "."
        )
        return

    if data == "admin_pending":
        await show_pending_orders(query.message)
        return

    if data == "admin_stats":
        await show_stats(query.message)
        return

    if data == "admin_recent":
        await show_recent_orders(query.message)
        return

    if data.startswith("approve:"):
        order_id = data.split(":", 1)[1]

        result = approve_order(order_id)

        await query.message.reply_text(
            result["admin_message"]
        )

        if result["user_id"] and result["user_text"]:
            try:
                await context.bot.send_message(
                    chat_id=result["user_id"],
                    text=result["user_text"],
                    parse_mode=ParseMode.HTML,
                    reply_markup=voucher_keyboard(),
                )
            except Exception:
                logger.exception(
                    "Could not deliver voucher to user"
                )

        return

    if data.startswith("reject:"):
        order_id = data.split(":", 1)[1]

        result = reject_order(order_id)

        await query.message.reply_text(
            result["admin_message"]
        )

        if result["user_id"]:
            try:
                await context.bot.send_message(
                    chat_id=result["user_id"],
                    text=(
                        "❌ Your payment/order was rejected.\n"
                        "Order ID: " + order_id
                    ),
                )
            except Exception:
                logger.exception(
                    "Could not notify user"
                )

        return


# ============================================================
# ADMIN PENDING ORDERS
# ============================================================
async def show_pending_orders(message):
    with db_lock:
        conn = get_db()

        rows = conn.execute("""
            SELECT order_id, user_id, username,
                   utr, amount, created_at
            FROM orders
            WHERE status='pending'
            ORDER BY id ASC
            LIMIT 20
        """).fetchall()

        conn.close()

    if not rows:
        await message.reply_text(
            "🧾 No pending orders."
        )
        return

    for row in rows:
        text = (
            "🧾 Pending Order\n\n"
            "Order ID: " + row["order_id"] + "\n"
            "User ID: " + str(row["user_id"]) + "\n"
            "Username: " + (row["username"] or "N/A") + "\n"
            "Amount: ₹" + str(row["amount"]) + "\n"
            "UTR: " + row["utr"] + "\n"
            "Time: " + row["created_at"]
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data="approve:" + row["order_id"],
                ),
                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data="reject:" + row["order_id"],
                ),
            ]
        ])

        await message.reply_text(
            text,
            reply_markup=keyboard,
        )


# ============================================================
# ADMIN STATISTICS
# ============================================================
async def show_stats(message):
    with db_lock:
        conn = get_db()

        total = conn.execute(
            "SELECT COUNT(*) n FROM orders"
        ).fetchone()["n"]

        approved = conn.execute(
            "SELECT COUNT(*) n FROM orders "
            "WHERE status='approved'"
        ).fetchone()["n"]

        rejected = conn.execute(
            "SELECT COUNT(*) n FROM orders "
            "WHERE status='rejected'"
        ).fetchone()["n"]

        pending = conn.execute(
            "SELECT COUNT(*) n FROM orders "
            "WHERE status='pending'"
        ).fetchone()["n"]

        sold = conn.execute(
            "SELECT COUNT(*) n FROM vouchers "
            "WHERE status='sold'"
        ).fetchone()["n"]

        added = conn.execute(
            "SELECT COUNT(*) n FROM vouchers"
        ).fetchone()["n"]

        revenue = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) n "
            "FROM orders WHERE status='approved'"
        ).fetchone()["n"]

        conn.close()

    await message.reply_text(
        "📊 Sales Statistics\n\n"
        "Total Orders: " + str(total) + "\n"
        "Approved: " + str(approved) + "\n"
        "Rejected: " + str(rejected) + "\n"
        "Pending: " + str(pending) + "\n"
        "Vouchers Added: " + str(added) + "\n"
        "Vouchers Sold: " + str(sold) + "\n"
        "Current Stock: " + str(available_stock()) + "\n"
        "Total Revenue: ₹" + str(revenue)
    )


# ============================================================
# ADMIN RECENT ORDERS
# ============================================================
async def show_recent_orders(message):
    with db_lock:
        conn = get_db()

        rows = conn.execute("""
            SELECT order_id, user_id, amount,
                   status, created_at
            FROM orders
            ORDER BY id DESC
            LIMIT 15
        """).fetchall()

        conn.close()

    if not rows:
        await message.reply_text(
            "📋 No orders yet."
        )
        return

    for row in rows:
        await message.reply_text(
            "📋 Order\n\n"
            "Order ID: " + row["order_id"] + "\n"
            "User ID: " + str(row["user_id"]) + "\n"
            "Amount: ₹" + str(row["amount"]) + "\n"
            "Status: " + row["status"] + "\n"
            "Date: " + row["created_at"]
        )


# ============================================================
# ORDER APPROVAL
# ============================================================
def approve_order(order_id):
    with db_lock:
        conn = get_db()

        try:
            conn.execute("BEGIN IMMEDIATE")

            order = conn.execute(
                "SELECT * FROM orders WHERE order_id=?",
                (order_id,),
            ).fetchone()

            if not order:
                conn.rollback()
                return {
                    "admin_message": "Order not found.",
                    "user_id": None,
                    "user_text": None,
                }

            if order["status"] != "pending":
                conn.rollback()
                return {
                    "admin_message":
                        "Order " + order_id +
                        " is already " +
                        order["status"] + ".",
                    "user_id": order["user_id"],
                    "user_text": None,
                }

            voucher = conn.execute("""
                SELECT id, code
                FROM vouchers
                WHERE status='available'
                ORDER BY id ASC
                LIMIT 1
            """).fetchone()

            if not voucher:
                conn.rollback()

                return {
                    "admin_message":
                        "Cannot approve. Voucher stock is empty.",
                    "user_id": order["user_id"],
                    "user_text": None,
                }

            t = now()

            conn.execute("""
                UPDATE vouchers
                SET status='sold',
                    sold_at=?,
                    order_id=?
                WHERE id=?
                  AND status='available'
            """, (
                t,
                order_id,
                voucher["id"],
            ))

            if conn.execute(
                "SELECT changes()"
            ).fetchone()[0] != 1:
                conn.rollback()

                return {
                    "admin_message":
                        "Voucher assignment failed. Try again.",
                    "user_id": order["user_id"],
                    "user_text": None,
                }

            conn.execute("""
                UPDATE orders
                SET status='approved',
                    voucher_code=?,
                    updated_at=?
                WHERE order_id=?
                  AND status='pending'
            """, (
                voucher["code"],
                t,
                order_id,
            ))

            if conn.execute(
                "SELECT changes()"
            ).fetchone()[0] != 1:
                conn.rollback()

                return {
                    "admin_message":
                        "Order update failed. Try again.",
                    "user_id": order["user_id"],
                    "user_text": None,
                }

            conn.commit()

            name = get_setting("product_name")
            terms = get_setting("terms")
            code = voucher["code"]

            safe_name = (
                name.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

            safe_code = (
                code.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

            safe_terms = (
                terms.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

            user_text = (
                "🎉 Voucher Delivered!\n\n"
                "🎟️ " + safe_name + "\n\n"
                "🎁 Voucher Code:\n"
                "<code>" + safe_code + "</code>\n\n"
                "📜 Terms & Conditions:\n"
                + safe_terms +
                "\n\n"
                "Order ID: " + order_id +
                "\n\n"
                "Tap/hold the voucher code to copy it."
            )

            return {
                "admin_message":
                    "✅ Order approved.\n"
                    "Order ID: " + order_id +
                    "\nVoucher delivered.",
                "user_id": order["user_id"],
                "user_text": user_text,
            }

        except Exception:
            conn.rollback()
            logger.exception(
                "Approve order failed"
            )

            return {
                "admin_message":
                    "An error occurred while approving the order.",
                "user_id": None,
                "user_text": None,
            }

        finally:
            conn.close()


# ============================================================
# ORDER REJECTION
# ============================================================
def reject_order(order_id):
    with db_lock:
        conn = get_db()

        try:
            conn.execute("BEGIN IMMEDIATE")

            order = conn.execute(
                "SELECT * FROM orders WHERE order_id=?",
                (order_id,),
            ).fetchone()

            if not order:
                conn.rollback()

                return {
                    "admin_message": "Order not found.",
                    "user_id": None,
                }

            if order["status"] != "pending":
                conn.rollback()

                return {
                    "admin_message":
                        "Order " + order_id +
                        " is already " +
                        order["status"] + ".",
                    "user_id": order["user_id"],
                }

            conn.execute("""
                UPDATE orders
                SET status='rejected',
                    updated_at=?
                WHERE order_id=?
                  AND status='pending'
            """, (
                now(),
                order_id,
            ))

            conn.commit()

            return {
                "admin_message":
                    "❌ Order rejected.\n"
                    "Order ID: " + order_id,
                "user_id": order["user_id"],
            }

        except Exception:
            conn.rollback()
            logger.exception(
                "Reject order failed"
            )

            return {
                "admin_message":
                    "An error occurred while rejecting the order.",
                "user_id": None,
            }

        finally:
            conn.close()


# ============================================================
# TEXT MESSAGE HANDLER
# ============================================================
async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    save_user(user)

    text = update.message.text.strip()
    state = context.user_data.get("state")

    # --------------------------------------------------------
    # ADMIN STATES
    # --------------------------------------------------------
    if user.id == ADMIN_ID:

        if state == "admin_broadcast":
            context.user_data.pop("state", None)

            with db_lock:
                conn = get_db()
                rows = conn.execute(
                    "SELECT user_id FROM users"
                ).fetchall()
                conn.close()

            sent = 0
            failed = 0

            for row in rows:
                try:
                    await context.bot.send_message(
                        chat_id=row["user_id"],
                        text=text,
                    )
                    sent += 1
                except Exception as exc:
                    failed += 1
                    logger.warning(
                        "Broadcast failed for %s: %s",
                        row["user_id"],
                        exc,
                    )

            await update.message.reply_text(
                "📢 Broadcast completed.\n\n"
                "Sent: " + str(sent) + "\n"
                "Failed: " + str(failed),
                reply_markup=admin_keyboard(),
            )
            return

        if state == "admin_add_vouchers":
            codes = [
                line.strip()
                for line in text.splitlines()
                if line.strip()
            ]

            added = 0
            duplicates = 0

            with db_lock:
                conn = get_db()

                for code in codes:
                    try:
                        conn.execute("""
                            INSERT INTO vouchers(
                                code, status, created_at
                            )
                            VALUES(?, 'available', ?)
                        """, (
                            code,
                            now(),
                        ))

                        added += 1

                    except sqlite3.IntegrityError:
                        duplicates += 1

                conn.commit()
                conn.close()

            context.user_data.pop("state", None)

            await update.message.reply_text(
                "✅ Voucher stock updated.\n"
                "Added: " + str(added) + "\n"
                "Duplicates skipped: " +
                str(duplicates) + "\n"
                "Current stock: " +
                str(available_stock()),
                reply_markup=admin_keyboard(),
            )

            return

        if state == "admin_price":
            try:
                price = float(text)

                if price <= 0:
                    raise ValueError

            except ValueError:
                await update.message.reply_text(
                    "Invalid price. Example: 25"
                )
                return

            value = (
                str(int(price))
                if price.is_integer()
                else f"{price:.2f}"
            )

            set_setting("price", value)
            context.user_data.pop("state", None)

            await update.message.reply_text(
                "✅ Price updated to ₹" + value,
                reply_markup=admin_keyboard(),
            )

            return

        if state == "admin_name":
            if len(text) > 200:
                await update.message.reply_text(
                    "Voucher name is too long."
                )
                return

            set_setting("product_name", text)
            context.user_data.pop("state", None)

            await update.message.reply_text(
                "✅ Voucher name updated.",
                reply_markup=admin_keyboard(),
            )

            return

        if state == "admin_terms":
            if len(text) > 4000:
                await update.message.reply_text(
                    "T&C is too long."
                )
                return

            set_setting("terms", text)
            context.user_data.pop("state", None)

            await update.message.reply_text(
                "✅ Terms & Conditions updated.",
                reply_markup=admin_keyboard(),
            )

            return

        if state == "admin_upi":
            if len(text) > 150:
                await update.message.reply_text(
                    "UPI ID is too long."
                )
                return

            set_setting("upi_id", text)
            context.user_data.pop("state", None)

            await update.message.reply_text(
                "✅ UPI ID updated.\n\n"
                "UPI ID:\n" +
                text,
                reply_markup=admin_keyboard(),
            )

            return

    # --------------------------------------------------------
    # USER UTR STATE
    # --------------------------------------------------------
    if state == "waiting_utr":

        if len(text) < 6 or len(text) > 100:
            await update.message.reply_text(
                "Please send a valid UTR / transaction ID."
            )
            return

        if get_setting("sales_enabled") != "1":
            context.user_data.pop("state", None)

            await update.message.reply_text(
                "🔴 Sales are currently unavailable."
            )

            return

        if available_stock() <= 0:
            context.user_data.pop("state", None)

            await update.message.reply_text(
                "❌ Sorry, the voucher is now out of stock."
            )

            return

        try:
            amount = float(get_setting("price"))
        except ValueError:
            await update.message.reply_text(
                "Product price is configured incorrectly."
            )
            return

        with db_lock:
            conn = get_db()

            existing = conn.execute("""
                SELECT order_id
                FROM orders
                WHERE utr=?
                  AND status IN ('pending', 'approved')
            """, (text,)).fetchone()

            if existing:
                conn.close()
                context.user_data.pop("state", None)

                await update.message.reply_text(
                    "This UTR has already been submitted.\n"
                    "Order ID: " +
                    existing["order_id"]
                )

                return

            order_id = generate_order_id(conn)
            t = now()

            conn.execute("""
                INSERT INTO orders(
                    order_id,
                    user_id,
                    username,
                    utr,
                    amount,
                    status,
                    created_at,
                    updated_at
                )
                VALUES(
                    ?, ?, ?, ?, ?,
                    'pending', ?, ?
                )
            """, (
                order_id,
                user.id,
                user.username or "",
                text,
                amount,
                t,
                t,
            ))

            conn.commit()
            conn.close()

        context.user_data.pop("state", None)

        await update.message.reply_text(
            "✅ Payment details submitted.\n\n"
            "Order ID: " + order_id + "\n"
            "Status: Pending admin approval.\n\n"
            "You will receive the voucher after approval."
        )

        if ADMIN_ID:
            try:
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ Approve",
                            callback_data="approve:" + order_id,
                        ),
                        InlineKeyboardButton(
                            "❌ Reject",
                            callback_data="reject:" + order_id,
                        ),
                    ]
                ])

                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        "🧾 New Voucher Order\n\n"
                        "Order ID: " + order_id + "\n"
                        "User ID: " + str(user.id) + "\n"
                        "Username: " +
                        (user.username or "N/A") + "\n"
                        "Amount: ₹" +
                        get_setting("price") + "\n"
                        "UTR: " + text
                    ),
                    reply_markup=keyboard,
                )

            except Exception:
                logger.exception(
                    "Could not notify admin"
                )

        return

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------
    if user.id == ADMIN_ID:
        await update.message.reply_text(
            "Use /admin to open the admin panel.",
            reply_markup=admin_keyboard(),
        )
    else:
        await update.message.reply_text(
            product_text(),
            reply_markup=main_keyboard(),
        )


# ============================================================
# ERROR HANDLER
# ============================================================
async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    logger.exception(
        "Unhandled bot error",
        exc_info=context.error
    )


# ============================================================
# MAIN
# ============================================================
def main():
    init_db()

    if (
        not BOT_TOKEN
        or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE"
    ):
        print(
            "ERROR: Put your Telegram bot token "
            "in BOT_TOKEN first."
        )
        return

    if not ADMIN_ID:
        print(
            "ERROR: Put your numeric Telegram Admin ID "
            "in ADMIN_ID first."
        )
        return

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("admin", admin_command)
    )

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    application.add_error_handler(error_handler)

    print("Voucher bot is running...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
