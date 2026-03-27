import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "app.db")

DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    # ✅ If Supabase / Render DB exists
    if DATABASE_URL:
        return psycopg2.connect(
            DATABASE_URL,
            sslmode="require",
            cursor_factory=RealDictCursor
        )

    # ✅ Else fallback to SQLite (local)
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
        timeout=30
    )
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def placeholder():
    return "%s" if DATABASE_URL else "?"


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # 🔥 Compatible SQL for both
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            product_name TEXT,
            sheet_name TEXT,
            active INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id SERIAL PRIMARY KEY,
            po_number TEXT,
            product_id INTEGER,
            customer TEXT,
            po_date TEXT,
            status TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            id SERIAL PRIMARY KEY,
            product_id INTEGER,
            item TEXT,
            vendor_name TEXT,
            order_date TEXT,
            order_status TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS po_steps (
            id SERIAL PRIMARY KEY,
            po_id INTEGER,
            step_index INTEGER,
            step_description TEXT,
            status TEXT,
            remark TEXT,
            updated_on TEXT
        )
    """)

    conn.commit()
    conn.close()
