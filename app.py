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
st.session_state.setdefault("active_po_number", None)        # store label for breadcrumb
st.session_state.setdefault("confirm_delete_pid", None)      # product pending deletion
st.session_state.setdefault("last_added_product", None)      # force sidebar to show new product
st.session_state.setdefault("confirm_delete_po_id", None)    # PO pending deletion
st.session_state.setdefault("confirm_delete_po_number", None)
st.session_state.setdefault("deleted_po_snapshot", None)     # holds deleted PO + steps for undo

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

        name   = c1.text_input("Name",  row["product_name"], key=f"name_{pid}")
        sheet  = c2.text_input("Sheet", row["sheet_name"],   key=f"sheet_{pid}")
        active = c3.checkbox("Active",  bool(row["active"]), key=f"active_{pid}")

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
            st.session_state.confirm_delete_pid = pid

    # ── Confirmation dialog rendered outside the column loop ──
    if st.session_state.confirm_delete_pid is not None:
        cpid  = st.session_state.confirm_delete_pid
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
        pname  = st.text_input("Product Name")
        sname  = st.text_input("Google Sheet Name")
        submit = st.form_submit_button("Add Product")

    if submit and pname.strip() and sname.strip():
        exec_query(
            f"INSERT INTO products (product_name, sheet_name, active) VALUES ({ph}, {ph}, 1)",
            (pname.strip(), sname.strip())
        )
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

    # Writing directly into session state BEFORE the selectbox renders is the
    # only reliable way to override a keyed widget in Streamlit.
    # Using `index=` is ignored when the key already exists in session state.

    # Force-select a newly added product
    if st.session_state.last_added_product in product_names:
        st.session_state.selected_product   = st.session_state.last_added_product
        st.session_state.last_added_product = None   # consume the flag

    # Fallback: if stored value no longer exists (e.g. product deleted), reset to first
    if st.session_state.selected_product not in product_names:
        st.session_state.selected_product = product_names[0]

    st.sidebar.selectbox("Select Product", product_names, key="selected_product")

    selected   = st.session_state.selected_product
    product_df = products[products["product_name"] == selected]

    # ── If the product changed, reset steps view so a stale sheet_name
    #    is never used to seed steps for a new PO ──
    if st.session_state.get("_last_product") != selected:
        go_back()   # clears view_mode, active_po_id, active_po_number
        st.session_state["_last_product"] = selected

    if product_df.empty:
        st.warning("Please select a product")
        st.stop()

    product    = product_df.iloc[0]
    product_id = int(product["id"])
    sheet_name = product["sheet_name"]

    # ── If the user switched product while in steps view, return to orders ──
    if st.session_state.view_mode == "steps" and st.session_state.active_po_id is not None:
        belongs = exec_query(
            f"SELECT 1 FROM purchase_orders WHERE id={ph} AND product_id={ph}",
            (st.session_state.active_po_id, product_id),
            fetch=True
        )
        if not belongs:
            go_back()

    # ================= BREADCRUMB & BACK NAVIGATION =================
    if st.session_state.view_mode == "steps":
        crumb_col, back_col = st.columns([8, 1])
        with crumb_col:
            st.markdown(f"**{product['product_name']}** › `{st.session_state.active_po_number or 'PO'}`")
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

            # ── Column headers ──
            h1, h2, h3, h4, h5 = st.columns([2, 2, 1.5, 2, 0.5])
            h1.markdown("**PO Number**")
            h2.markdown("**Customer**")
            h3.markdown("**Date**")
            h4.markdown("**Status**")
            h5.markdown("**Del**")

            # ── One row per PO ──
            for _, row in orders.iterrows():
                po_id_row = int(row["id"])
                c1, c2, c3, c4, c5 = st.columns([2, 2, 1.5, 2, 0.5])

                c1.write(row["po_number"])
                c2.write(row["customer"] or "—")
                c3.write(pd.to_datetime(row["po_date"]).strftime("%d/%m/%y"))

                new_status = c4.selectbox(
                    "status",
                    ORDER_STATUSES,
                    index=ORDER_STATUSES.index(row["status"]) if row["status"] in ORDER_STATUSES else 0,
                    key=f"status_{po_id_row}",
                    label_visibility="collapsed"
                )
                if new_status != row["status"]:
                    exec_query(
                        f"UPDATE purchase_orders SET status={ph} WHERE id={ph}",
                        (new_status, po_id_row)
                    )

                # ── Delete button — sets pending state, does NOT delete immediately ──
                if c5.button("🗑", key=f"del_po_{po_id_row}", help="Delete this PO"):
                    st.session_state.confirm_delete_po_id     = po_id_row
                    st.session_state.confirm_delete_po_number = row["po_number"]

            # ── PO deletion confirmation banner (outside the row loop) ──
            if st.session_state.confirm_delete_po_id is not None:
                po_label = st.session_state.confirm_delete_po_number
                st.warning(
                    f"⚠️ Delete PO **{po_label}**? "
                    "This will also remove all its steps. You can undo immediately after."
                )
                yes_col, no_col, _ = st.columns([1, 1, 6])
                if yes_col.button("✅ Yes, delete", key="confirm_po_yes"):
                    del_id = st.session_state.confirm_delete_po_id
                    # Snapshot PO + steps before deleting so undo is possible
                    po_row = exec_query(
                        f"SELECT id, po_number, product_id, customer, po_date, status FROM purchase_orders WHERE id={ph}",
                        (del_id,), fetch=True
                    )
                    steps_rows = exec_query(
                        f"SELECT step_index, step_description, status, remark, updated_on FROM po_steps WHERE po_id={ph} ORDER BY step_index",
                        (del_id,), fetch=True
                    )
                    st.session_state.deleted_po_snapshot = {
                        "po":    po_row[0] if po_row else None,
                        "steps": steps_rows
                    }
                    exec_query(f"DELETE FROM po_steps WHERE po_id={ph}", (del_id,))
                    exec_query(f"DELETE FROM purchase_orders WHERE id={ph}", (del_id,))
                    st.session_state.confirm_delete_po_id     = None
                    st.session_state.confirm_delete_po_number = None
                    st.toast(f"PO '{po_label}' deleted. Click Undo to restore.", icon="🗑️")
                    st.rerun()
                if no_col.button("❌ Cancel", key="confirm_po_no"):
                    st.session_state.confirm_delete_po_id     = None
                    st.session_state.confirm_delete_po_number = None
                    st.rerun()

            # Undo banner shown after deletion until user restores or dismisses
            if st.session_state.deleted_po_snapshot is not None:
                snap    = st.session_state.deleted_po_snapshot
                po_data = snap["po"]
                if po_data:
                    undo_label = po_data[1]
                    st.info(f"🗑️ PO **{undo_label}** was deleted.")
                    undo_col, dismiss_col, _ = st.columns([1, 1, 6])
                    if undo_col.button("↩️ Undo", key="undo_po"):
                        exec_query(
                            f"INSERT INTO purchase_orders (po_number, product_id, customer, po_date, status) VALUES ({ph}, {ph}, {ph}, {ph}, {ph})",
                            (po_data[1], po_data[2], po_data[3], po_data[4], po_data[5])
                        )
                        new_po_id_row = exec_query(
                            f"SELECT id FROM purchase_orders WHERE po_number={ph} AND product_id={ph} ORDER BY id DESC LIMIT 1",
                            (po_data[1], po_data[2]), fetch=True
                        )
                        if new_po_id_row:
                            new_po_id = new_po_id_row[0][0]
                            for s in snap["steps"]:
                                exec_query(
                                    f"INSERT INTO po_steps (po_id, step_index, step_description, status, remark, updated_on) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})",
                                    (new_po_id, s[0], s[1], s[2], s[3], s[4])
                                )
                        st.session_state.deleted_po_snapshot = None
                        st.toast(f"PO '{undo_label}' restored!", icon="↩️")
                        st.rerun()
                    if dismiss_col.button("✖ Dismiss", key="dismiss_undo"):
                        st.session_state.deleted_po_snapshot = None
                        st.rerun()

        st.divider()

        active_orders = orders[orders["status"] != "Cancelled"] if not orders.empty else orders
        if not active_orders.empty:
            po_map      = {row["po_number"]: int(row["id"]) for _, row in active_orders.iterrows()}
            selected_po = st.selectbox("Select PO to Track", list(po_map.keys()))

            if st.button("Track Selected PO"):
                st.session_state.active_po_id     = po_map[selected_po]
                st.session_state.active_po_number = selected_po
                st.session_state.view_mode        = "steps"
                st.rerun()

        st.divider()

        with st.form("add_order"):
            po      = st.text_input("PO Number")
            cust    = st.text_input("Customer")
            po_date = st.date_input("PO Date", value=date.today())
            status  = st.selectbox("Status", ORDER_STATUSES)
            submit  = st.form_submit_button("Add Order")

        if submit and po.strip():
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
                    INSERT INTO purchase_orders (po_number, product_id, customer, po_date, status)
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
                    INSERT INTO po_steps (po_id, step_index, step_description, status)
                    VALUES ({ph}, {ph}, {ph}, 'Not Started')
                    """,
                    (po_id, i, step["description"])
                )
            steps = fetch_po_steps(po_id)

        display = pd.DataFrame({
            "Done": steps["status"] == "Done",
            "Date": steps.apply(
                lambda r: datetime.fromisoformat(r["updated_on"]).strftime("%d/%m/%y")
                          if r["updated_on"] else "",
                axis=1
            ),
            "Description": steps["step_description"],
            "Remark":      steps["remark"].fillna("")
        })

        edited = st.data_editor(
            display,
            use_container_width=True,
            num_rows="fixed",
            column_config={
                "Date": st.column_config.TextColumn(disabled=True),
            }
        )

        needs_rerun = False

        for i, row in steps.iterrows():
            ed       = edited.iloc[i]
            new_done = ed["Done"]
            was_done = row["status"] == "Done"

            if new_done:
                new_status = "Done"
                new_date   = row["updated_on"] if was_done and row["updated_on"] else date.today().isoformat()
            else:
                new_status = "Not Started"
                new_date   = None

            if (
                new_status != row["status"]
                or ed["Description"] != row["step_description"]
                or ed["Remark"] != (row["remark"] or "")
                or new_date != row["updated_on"]
            ):
                exec_query(
                    f"""
                    UPDATE po_steps
                    SET step_description={ph}, status={ph}, remark={ph}, updated_on={ph}
                    WHERE id={ph}
                    """,
                    (ed["Description"], new_status, ed["Remark"], new_date, int(row["id"]))
                )
                if new_done != was_done:
                    needs_rerun = True

        if needs_rerun:
            st.rerun()

        # ── Add a custom step row ──
        st.divider()
        with st.form("add_step"):
            new_desc = st.text_input("Step Description", placeholder="Enter new step...")
            new_rmk  = st.text_input("Remark (optional)")
            add_step = st.form_submit_button("➕ Add Step")

        if add_step and new_desc.strip():
            # Next index = current max + 1
            next_idx = int(steps["step_index"].max()) + 1 if not steps.empty else 1
            exec_query(
                f"""
                INSERT INTO po_steps (po_id, step_index, step_description, status, remark)
                VALUES ({ph}, {ph}, {ph}, 'Not Started', {ph})
                """,
                (po_id, next_idx, new_desc.strip(), new_rmk.strip() or None)
            )
            st.toast("Step added.", icon="✅")
            st.rerun()
