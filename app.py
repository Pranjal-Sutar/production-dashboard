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
st.session_state.setdefault("active_po_number", None)       # store label for breadcrumb
st.session_state.setdefault("confirm_delete_pid", None)     # product pending deletion
st.session_state.setdefault("last_added_product", None)     # force sidebar to show new product

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


def go_back():
    """Reset to orders view and clear active PO."""
    st.session_state.view_mode = "orders"
    st.session_state.active_po_id = None
    st.session_state.active_po_number = None


# ================= SIDEBAR =================
st.sidebar.header("Mode")
st.session_state.mode = st.sidebar.radio("Select Mode", ["Operations", "Admin"])


# ================= ADMIN =================
if st.session_state.mode == "Admin":

    # ---------- PRODUCTS ----------
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
            # First click → ask for confirmation
            st.session_state.confirm_delete_pid = pid

    # ── Confirmation dialog rendered outside the column loop ──
    if st.session_state.confirm_delete_pid is not None:
        cpid = st.session_state.confirm_delete_pid
        cname = products.loc[products["id"] == cpid, "product_name"].values
        label = cname[0] if len(cname) else f"ID {cpid}"
        st.warning(f"⚠️ Are you sure you want to delete **{label}**? This cannot be undone.")
        yes_col, no_col, _ = st.columns([1, 1, 6])
        if yes_col.button("✅ Yes, delete", key="confirm_yes"):
            exec_query(f"DELETE FROM products WHERE id={ph}", (cpid,))
            st.session_state.confirm_delete_pid = None
            st.toast(f"'{label}' deleted.", icon="🗑️")
            st.rerun()
        if no_col.button("❌ Cancel", key="confirm_no"):
            st.session_state.confirm_delete_pid = None
            st.rerun()

    st.divider()
    st.subheader("Want to add a new product? Follow the steps below")

    # ---------- GUIDE ----------
    st.info("""

**1️⃣ Google Sheet Structure**
- First **3 rows** can be headers / notes (ignored)
- Actual steps must start from **row 4**
- Step description must be in **column C**

**2️⃣ Share the Sheet**
Share the Google Sheet with this **service account email** as **Editor**:

📧 **SERVICE ACCOUNT EMAIL**  
``

*(This is a system account, not a personal Gmail)*

**3️⃣ Link Sheet to Product**
- Enter the **exact Google Sheet name**
- Click **Save**
- Steps will auto-load for every PO of this product

ℹ️ If the sheet name changes later, just update it here — no code changes needed.
""")

    st.divider()

    # ---------- ADD PRODUCT ----------
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
        # ── Remember this product so Operations sidebar shows it immediately ──
        st.session_state.last_added_product = pname.strip()
        st.toast(f"Product '{pname.strip()}' added successfully!", icon="✅")
        st.rerun()


# ================= OPERATIONS =================
if st.session_state.mode == "Operations":

    products = fetch_products()
    if products.empty:
        st.warning("No active products")
        st.stop()

    product_names = products["product_name"].tolist()

    # ── If a brand-new product was just added, force-select it ──
    if st.session_state.last_added_product in product_names:
        default_idx = product_names.index(st.session_state.last_added_product)
        st.session_state.last_added_product = None   # consume the flag
    elif st.session_state.selected_product in product_names:
        default_idx = product_names.index(st.session_state.selected_product)
    else:
        default_idx = 0

    st.sidebar.selectbox("Select Product", product_names, index=default_idx, key="selected_product")

    selected = st.session_state.selected_product
    product_df = products[products["product_name"] == selected]

    if product_df.empty:
        st.warning("Please select a product")
        st.stop()

    product = product_df.iloc[0]
    product_id = int(product["id"])
    sheet_name = product["sheet_name"]

    # ── If the user switched product while in steps view, go back to orders ──
    if (
        st.session_state.view_mode == "steps"
        and st.session_state.active_po_id is not None
    ):
        # Check the active PO actually belongs to this product
        belongs = exec_query(
            f"SELECT 1 FROM purchase_orders WHERE id={ph} AND product_id={ph}",
            (st.session_state.active_po_id, product_id),
            fetch=True
        )
        if not belongs:
            go_back()

    # ================= BREADCRUMB & BACK NAVIGATION =================
    if st.session_state.view_mode == "steps":
        # Breadcrumb: Product > PO Number
        crumb_col, back_col = st.columns([8, 1])
        with crumb_col:
            st.markdown(
                f"**{product['product_name']}** › `{st.session_state.active_po_number or 'PO'}`"
            )
        with back_col:
            if st.button("⬅ Back", use_container_width=True):
                go_back()
                st.rerun()
        st.divider()

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
                    "status": st.column_config.SelectboxColumn(options=ORDER_STATUSES)
                }
            )

            for i in range(len(edited)):
                if edited.iloc[i]["status"] != orders.iloc[i]["status"]:
                    exec_query(
                        f"UPDATE purchase_orders SET status={ph} WHERE id={ph}",
                        (edited.iloc[i]["status"], int(orders.iloc[i]["id"]))
                    )

        st.divider()

        active_orders = orders[orders["status"] != "Cancelled"] if not orders.empty else orders
        if not active_orders.empty:
            po_map = {row["po_number"]: int(row["id"]) for _, row in active_orders.iterrows()}
            selected_po = st.selectbox("Select PO to Track", list(po_map.keys()))

            if st.button("Track Selected PO"):
                st.session_state.active_po_id = po_map[selected_po]
                st.session_state.active_po_number = selected_po   # ← save label
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
            # ── Guard: prevent duplicate PO numbers for the same product ──
            existing = exec_query(
                f"SELECT 1 FROM purchase_orders WHERE po_number={ph} AND product_id={ph}",
                (po.strip(), product_id),
                fetch=True
            )
            if existing:
                st.error(f"PO number **{po.strip()}** already exists for this product.")
            else:
                exec_query(
                    f"""
                    INSERT INTO purchase_orders
                    (po_number, product_id, customer, po_date, status)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph})
                    """,
                    (po.strip(), product_id, cust.strip(), po_date.isoformat(), status)
                )
                st.toast(f"PO '{po.strip()}' added successfully!", icon="✅")
                st.rerun()

    # ================= STEPS =================
    if st.session_state.view_mode == "steps":

        po_id = int(st.session_state.active_po_id)
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

        today_str = date.today().strftime("%d/%m/%y")

        display = pd.DataFrame({
            "Done": steps["status"] == "Done",
            # ── KEY FIX: if Done show saved date, else show today's date as a preview ──
            "Date": steps.apply(
                lambda r: (
                    datetime.fromisoformat(r["updated_on"]).strftime("%d/%m/%y")
                    if r["updated_on"]
                    else ""
                ),
                axis=1
            ),
            "Description": steps["step_description"],
            "Remark": steps["remark"].fillna("")
        })

        edited = st.data_editor(
            display,
            use_container_width=True,
            num_rows="fixed",
            column_config={
                # Make Date read-only — it is set automatically
                "Date": st.column_config.TextColumn(disabled=True),
            }
        )

        needs_rerun = False

        for i, row in steps.iterrows():
            ed = edited.iloc[i]
            new_done = ed["Done"]
            was_done = row["status"] == "Done"

            # Determine new status and date
            if new_done:
                new_status = "Done"
                # Preserve original completion date if already done; otherwise stamp today
                new_date = row["updated_on"] if was_done and row["updated_on"] else date.today().isoformat()
            else:
                new_status = "Not Started"
                new_date = None

            # Only write to DB when something actually changed
            if (
                new_status != row["status"]
                or ed["Description"] != row["step_description"]
                or ed["Remark"] != (row["remark"] or "")
                or new_date != row["updated_on"]
            ):
                exec_query(
                    f"""
                    UPDATE po_steps
                    SET step_description={ph},
                        status={ph},
                        remark={ph},
                        updated_on={ph}
                    WHERE id={ph}
                    """,
                    (ed["Description"], new_status, ed["Remark"], new_date, int(row["id"]))
                )
                # Rerun only when the Done checkbox changed so the Date column refreshes instantly
                if new_done != was_done:
                    needs_rerun = True

        if needs_rerun:
            st.rerun()
