# db.py
import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")


def is_postgres():
    return DATABASE_URL is not None


def get_connection():
    if is_postgres():
        return psycopg2.connect(
            DATABASE_URL,
            sslmode="require",
            cursor_factory=RealDictCursor
        )
    else:
        return sqlite3.connect(
            "database.db",
            check_same_thread=False
        )


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    if is_postgres():
        # ---------- POSTGRES ----------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                product_name TEXT NOT NULL,
                sheet_name TEXT NOT NULL,
                active INTEGER DEFAULT 1
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

    else:
        # ---------- SQLITE ----------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                sheet_name TEXT NOT NULL,
                active INTEGER DEFAULT 1
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_number TEXT,
                product_id INTEGER,
                customer TEXT,
                po_date TEXT,
                status TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS po_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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