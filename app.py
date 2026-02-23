import streamlit as st
import pandas as pd
from datetime import date, datetime

from db import init_db, get_connection
from sheets import get_steps_raw

# ================= CONSTANTS =================
ORDER_STATUSES = [
    "Not Started",
    "In Progress",
    "Completed",
    "Cancelled"
]

# ================= SESSION STATE =================
st.session_state.setdefault("mode", "Operations")
st.session_state.setdefault("selected_product", None)
st.session_state.setdefault("view_mode", "orders")
st.session_state.setdefault("active_po_id", None)

# ================= INIT =================
st.set_page_config(layout="wide")
init_db()

# ================= TOP BAR =================
col_back, col_title = st.columns([1, 9])

with col_back:
    if st.session_state.view_mode == "steps":
        if st.button("⬅ Back"):
            st.session_state.view_mode = "orders"
            st.session_state.active_po_id = None
            st.rerun()

with col_title:
    st.title("Production Management Dashboard")

# ================= DB HELPERS =================
def fetch_df(query, params=None):
    conn = get_connection()
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df


def exec_query(query, params=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params or [])
    conn.commit()
    conn.close()


# ================= SIDEBAR =================
st.sidebar.header("Mode")
st.session_state.mode = st.sidebar.radio(
    "Select Mode", ["Operations", "Admin"]
)

# ================= ADMIN =================
if st.session_state.mode == "Admin":

    st.subheader("🛠 Admin – Product Management")

    products = fetch_df(
        "SELECT id, product_name, sheet_name, active FROM products"
    )

    if products.empty:
        st.info("No products found.")

    for _, row in products.iterrows():
        c1, c2, c3, c4, c5 = st.columns([3, 3, 1.5, 1.5, 1])

        name = c1.text_input(
            "Product Name",
            value=row["product_name"],
            key=f"name_{row['id']}"
        )

        sheet = c2.text_input(
            "Sheet Name",
            value=row["sheet_name"],
            key=f"sheet_{row['id']}"
        )

        active = c3.checkbox(
            "Active",
            value=bool(row["active"]),
            key=f"active_{row['id']}"
        )

        if c4.button("💾 Save", key=f"save_{row['id']}"):
            exec_query(
                """
                UPDATE products
                SET product_name=?, sheet_name=?, active=?
                WHERE id=?
                """,
                (name.strip(), sheet.strip(), 1 if active else 0, row["id"])
            )
            st.success("Updated")
            st.rerun()

        if c5.button("🗑 Delete", key=f"delete_{row['id']}"):
            exec_query("DELETE FROM products WHERE id=?", (row["id"],))
            st.warning("Deleted (DB only, sheets untouched)")
            st.rerun()

    st.divider()

    with st.form("add_product"):
        pname = st.text_input("Product Name")
        sname = st.text_input("Google Sheet Name")
        submit = st.form_submit_button("Add Product")

    if submit:
        if pname.strip() and sname.strip():
            exec_query(
                """
                INSERT INTO products (product_name, sheet_name, active)
                VALUES (?, ?, 1)
                """,
                (pname.strip(), sname.strip())
            )
            st.success("Product added")
            st.rerun()
        else:
            st.error("Both fields required")

# ================= OPERATIONS =================
if st.session_state.mode == "Operations":

    products = fetch_df(
        "SELECT id, product_name, sheet_name FROM products WHERE active=1"
    )

    if products.empty:
        st.warning("No active products.")
        st.stop()

    product_names = products["product_name"].tolist()

    if st.session_state.selected_product not in product_names:
        st.session_state.selected_product = product_names[0]

    st.sidebar.selectbox(
        "Select Product",
        product_names,
        key="selected_product"
    )

    product = products[
        products["product_name"] == st.session_state.selected_product
    ].iloc[0]

    product_id = product["id"]
    sheet_name = product["sheet_name"]

    # ================= ORDERS =================
    if st.session_state.view_mode == "orders":

        st.subheader(f"📄 Orders – {product['product_name']}")

        orders = fetch_df(
            """
            SELECT id, po_number, customer, po_date, status
            FROM purchase_orders
            WHERE product_id=?
            ORDER BY po_date DESC
            """,
            (product_id,)
        )

        if not orders.empty:

            display = orders.rename(columns={
                "po_number": "PO Number",
                "customer": "Customer",
                "po_date": "PO Date",
                "status": "Status"
            })[["PO Number", "Customer", "PO Date", "Status"]]

            edited = st.data_editor(
                display,
                use_container_width=True,
                num_rows="fixed",
                column_config={
                    "Status": st.column_config.SelectboxColumn(
                        options=ORDER_STATUSES
                    )
                }
            )

            for i in range(len(edited)):
                if edited.iloc[i]["Status"] != orders.iloc[i]["status"]:
                    exec_query(
                        "UPDATE purchase_orders SET status=? WHERE id=?",
                        (edited.iloc[i]["Status"], orders.iloc[i]["id"])
                    )

            st.divider()

            active = orders[orders["status"] != "Cancelled"]

            if not active.empty:
                selected_po = st.selectbox(
                    "Select PO to Track",
                    active["po_number"].tolist()
                )

                if st.button("Track Selected PO"):
                    st.session_state.active_po_id = active[
                        active["po_number"] == selected_po
                    ]["id"].values[0]
                    st.session_state.view_mode = "steps"
                    st.rerun()
        else:
            st.info("No orders found.")

        st.divider()

        with st.form("add_order"):
            po = st.text_input("PO Number")
            customer = st.text_input("Customer")
            po_date = st.date_input("PO Date", value=date.today())
            status = st.selectbox("Status", ORDER_STATUSES)
            submit = st.form_submit_button("Add Order")

        if submit and po.strip():
            exec_query(
                """
                INSERT INTO purchase_orders
                (po_number, product_id, customer, po_date, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (po.strip(), product_id, customer.strip(),
                 po_date.isoformat(), status)
            )
            st.success("Order added")
            st.rerun()

# ================= STEPS =================
if st.session_state.view_mode == "steps":

    st.subheader(f"🛠 Steps – {product['product_name']}")

    steps = fetch_df(
        """
        SELECT id, step_index, step_description, status, remark, updated_on
        FROM po_steps
        WHERE po_id=?
        ORDER BY step_index
        """,
        (st.session_state.active_po_id,)
    )

    if steps.empty:
        raw = get_steps_raw(sheet_name)
        for i, step in enumerate(raw, start=1):
            exec_query(
                """
                INSERT INTO po_steps
                (po_id, step_index, step_description, status, remark, updated_on)
                VALUES (?, ?, ?, 'Not Started', '', NULL)
                """,
                (st.session_state.active_po_id, i, step["description"])
            )
        steps = fetch_df(
            "SELECT * FROM po_steps WHERE po_id=? ORDER BY step_index",
            (st.session_state.active_po_id,)
        )

    table = pd.DataFrame({
        "Done": steps["status"] == "Done",
        "Date": steps["updated_on"].apply(
            lambda d: datetime.fromisoformat(d).strftime("%d/%m/%y") if d else ""
        ),
        "Description": steps["step_description"],
        "Remark": steps["remark"].fillna("")
    })

    edited = st.data_editor(
        table,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "Done": st.column_config.CheckboxColumn(),
            "Date": st.column_config.TextColumn(disabled=True),
        }
    )

    for i in range(len(edited)):
        db = steps.iloc[i]
        ui = edited.iloc[i]

        new_status = "Done" if ui["Done"] else "Not Started"
        new_date = date.today().isoformat() if ui["Done"] else None

        if (
            new_status != db["status"]
            or ui["Description"] != db["step_description"]
            or ui["Remark"] != (db["remark"] or "")
        ):
            exec_query(
                """
                UPDATE po_steps
                SET step_description=?, status=?, remark=?, updated_on=?
                WHERE id=?
                """,
                (
                    ui["Description"],
                    new_status,
                    ui["Remark"],
                    new_date,
                    db["id"]
                )
            )