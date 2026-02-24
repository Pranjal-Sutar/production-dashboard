import streamlit as st
import pandas as pd
from datetime import date, datetime

from db import init_db, exec_query, placeholder
from sheets import get_steps_raw

# ================= CONFIG =================
st.set_page_config(layout="wide")
init_db()

ORDER_STATUSES = ["Not Started", "In Progress", "Completed", "Cancelled"]
ph = placeholder()

# ================= SESSION =================
st.session_state.setdefault("mode", "Operations")
st.session_state.setdefault("selected_product", None)
st.session_state.setdefault("view_mode", "orders")
st.session_state.setdefault("active_po_id", None)

# ================= HELPERS =================
def fetch_products(active_only=True):
    q = "SELECT id, product_name, sheet_name, active FROM products"
    if active_only:
        q += " WHERE active = 1"
    rows = exec_query(q, fetch=True)
    return pd.DataFrame(rows, columns=["id", "product_name", "sheet_name", "active"])


def fetch_orders(product_id):
    rows = exec_query(
        f"""
        SELECT id, po_number, customer, po_date, status
        FROM purchase_orders
        WHERE product_id = {ph}
        ORDER BY po_date DESC
        """,
        (int(product_id),),
        fetch=True
    )
    return pd.DataFrame(
        rows,
        columns=["id", "po_number", "customer", "po_date", "status"]
    )


def fetch_po_steps(po_id):
    rows = exec_query(
        f"""
        SELECT id, step_index, step_description, status, remark, updated_on
        FROM po_steps
        WHERE po_id = {ph}
        ORDER BY step_index
        """,
        (int(po_id),),
        fetch=True
    )
    return pd.DataFrame(
        rows,
        columns=["id", "step_index", "step_description", "status", "remark", "updated_on"]
    )


# ================= SIDEBAR =================
st.sidebar.header("Mode")
st.session_state.mode = st.sidebar.radio("Select Mode", ["Operations", "Admin"])

# ================= ADMIN =================
if st.session_state.mode == "Admin":
    st.subheader("🛠 Admin – Product Management")

    products = fetch_products(active_only=False)

    for _, row in products.iterrows():
        pid = int(row["id"])
        c1, c2, c3, c4, c5 = st.columns([3, 3, 1, 1, 1])

        name = c1.text_input("Name", row["product_name"], key=f"name_{pid}")
        sheet = c2.text_input("Sheet", row["sheet_name"], key=f"sheet_{pid}")
        active = c3.checkbox("Active", bool(row["active"]), key=f"active_{pid}")

        if c4.button("Save", key=f"save_{pid}"):
            exec_query(
                f"""
                UPDATE products
                SET product_name={ph}, sheet_name={ph}, active={ph}
                WHERE id={ph}
                """,
                (name.strip(), sheet.strip(), int(active), pid)
            )
            st.success("Updated")
            st.rerun()

        if c5.button("🗑", key=f"del_{pid}"):
            exec_query(f"DELETE FROM products WHERE id={ph}", (pid,))
            st.warning("Deleted")
            st.rerun()

    st.divider()

    with st.form("add_product"):
        pname = st.text_input("Product Name")
        sname = st.text_input("Google Sheet Name")
        submit = st.form_submit_button("Add Product")

    if submit and pname.strip() and sname.strip():
        exec_query(
            f"""
            INSERT INTO products (product_name, sheet_name, active)
            VALUES ({ph}, {ph}, 1)
            """,
            (pname.strip(), sname.strip())
        )
        st.success("Product added")
        st.rerun()

# ================= OPERATIONS =================
if st.session_state.mode == "Operations":

    products = fetch_products()
    if products.empty:
        st.warning("No active products")
        st.stop()

    product_names = products["product_name"].tolist()

    st.sidebar.selectbox(
        "Select Product",
        product_names,
        key="selected_product"
    )

    selected = st.session_state.selected_product
    product_df = products[products["product_name"] == selected]

    if product_df.empty:
        st.warning("Please select a product")
        st.stop()

    product = product_df.iloc[0]
    product_id = int(product["id"])
    sheet_name = product["sheet_name"]

    # ================= ORDERS =================
    if st.session_state.view_mode == "orders":
        st.subheader(f"📄 Orders – {product['product_name']}")

        orders = fetch_orders(product_id)

        if not orders.empty:
            display = orders[["po_number", "customer", "po_date", "status"]].copy()
            display["po_date"] = pd.to_datetime(display["po_date"]).dt.strftime("%d/%m/%y")

            edited = st.data_editor(
                display,
                use_container_width=True,
                num_rows="fixed",
                column_config={
                    "status": st.column_config.SelectboxColumn(
                        options=ORDER_STATUSES
                    )
                }
            )

            for i in range(len(edited)):
                if edited.iloc[i]["status"] != orders.iloc[i]["status"]:
                    exec_query(
                        f"UPDATE purchase_orders SET status={ph} WHERE id={ph}",
                        (
                            edited.iloc[i]["status"],
                            int(orders.iloc[i]["id"])
                        )
                    )

            st.divider()

            active_orders = orders[orders["status"] != "Cancelled"]
            if not active_orders.empty:
                po_map = {
                    row["po_number"]: int(row["id"])
                    for _, row in active_orders.iterrows()
                }

                selected_po = st.selectbox("Select PO to Track", list(po_map.keys()))

                if st.button("Track Selected PO"):
                    st.session_state.active_po_id = po_map[selected_po]
                    st.session_state.view_mode = "steps"
                    st.rerun()

        st.divider()

        with st.form("add_order"):
            po = st.text_input("PO Number")
            cust = st.text_input("Customer")
            po_date = st.date_input("PO Date", value=date.today())
            status = st.selectbox("Status", ORDER_STATUSES)
            submit = st.form_submit_button("Add Order")

        if submit and po.strip():
            exec_query(
                f"""
                INSERT INTO purchase_orders
                (po_number, product_id, customer, po_date, status)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph})
                """,
                (
                    po.strip(),
                    product_id,
                    cust.strip(),
                    po_date.isoformat(),
                    status
                )
            )
            st.success("Order added")
            st.rerun()

    # ================= STEPS =================
    if st.session_state.view_mode == "steps":
        po_id = st.session_state.active_po_id
        if not po_id:
            st.warning("No PO selected")
            st.stop()

        po_id = int(po_id)
        st.subheader("🛠 Steps")

        steps = fetch_po_steps(po_id)

        if steps.empty:
            raw = get_steps_raw(sheet_name)
            for i, step in enumerate(raw, start=1):
                exec_query(
                    f"""
                    INSERT INTO po_steps
                    (po_id, step_index, step_description, status)
                    VALUES ({ph}, {ph}, {ph}, 'Not Started')
                    """,
                    (po_id, i, step["description"])
                )
            steps = fetch_po_steps(po_id)

        display = pd.DataFrame({
            "Done": steps["status"] == "Done",
            "Date": steps["updated_on"].apply(
                lambda d: datetime.fromisoformat(d).strftime("%d/%m/%y") if d else ""
            ),
            "Description": steps["step_description"],
            "Remark": steps["remark"].fillna("")
        })

        edited = st.data_editor(display, use_container_width=True, num_rows="fixed")

        for i, row in steps.iterrows():
            ed = edited.iloc[i]
            new_status = "Done" if ed["Done"] else "Not Started"
            new_date = date.today().isoformat() if ed["Done"] else None

            exec_query(
                f"""
                UPDATE po_steps
                SET step_description={ph},
                    status={ph},
                    remark={ph},
                    updated_on={ph}
                WHERE id={ph}
                """,
                (
                    ed["Description"],
                    new_status,
                    ed["Remark"],
                    new_date,
                    int(row["id"])
                )
            )

