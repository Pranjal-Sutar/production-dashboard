# db.py
import os
import sqlite3
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")


def is_postgres():
    return DATABASE_URL is not None


def get_connection():
    if is_postgres():
        return psycopg2.connect(DATABASE_URL, sslmode="require")
    else:
        return sqlite3.connect("database.db")


def placeholder():
    """Return correct SQL placeholder for active DB"""
    return "%s" if is_postgres() else "?"


def exec_query(query, params=None, fetch=False):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params or [])
    data = None
    if fetch:
        data = cur.fetchall()
    conn.commit()
    conn.close()
    return data


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # PRODUCTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            product_name TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)

    # PURCHASE ORDERS
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

    # PO STEPS
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
