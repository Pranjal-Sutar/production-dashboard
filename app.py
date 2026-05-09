#last edited 05/05/26
import streamlit as st
import pandas as pd
from datetime import date, datetime
from db import get_connection
from supabase_client import supabase
from sheets import get_steps_raw
from dotenv import load_dotenv
load_dotenv()
import time
import re

st.set_page_config(layout="wide")

st.markdown("""
<style>
.overdue-row {
    background-color: #ffe5e5;
    padding: 4px 6px;
    border-radius: 6px;
    color: #b91c1c;
    font-weight: 500;
}
</style>
""", unsafe_allow_html=True)
import google.generativeai as genai
import os
if "show_chat" not in st.session_state:
    st.session_state.show_chat = False
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-flash-latest")
ORDER_STATUSES = ["Not Started", "In Progress", "Completed", "Cancelled"]


st.session_state.setdefault("mode", "Operations")
st.session_state.setdefault("selected_product", None)
st.session_state.setdefault("view_mode", "orders")
st.session_state.setdefault("active_po_id", None)
st.session_state.setdefault("active_po_number", None)        
st.session_state.setdefault("confirm_delete_pid", None)      
st.session_state.setdefault("last_added_product", None)      
st.session_state.setdefault("confirm_delete_po_id", None)    
st.session_state.setdefault("confirm_delete_po_number", None)
st.session_state.setdefault("deleted_po_snapshot", None)     
st.session_state.setdefault("last_api_call", 0)
st.session_state.setdefault("last_query", "")
st.session_state.setdefault("last_referenced_po", None)
st.session_state.setdefault("last_referenced_product", None)
st.session_state.setdefault("last_referenced_customer", None)
st.session_state.setdefault("is_processing", False)

def fetch_products(active_only=True):
    query = supabase.table("products").select("*")
    
    if active_only:
        query = query.eq("active", True)

    data = query.execute().data
    return pd.DataFrame(data)

def fetch_orders(product_id):
    data = supabase.table("purchase_orders") \
        .select("*") \
        .eq("product_id", int(product_id)) \
        .order("po_date", desc=True) \
        .execute().data

    return pd.DataFrame(data)

def fetch_po_steps(po_id):
    data = supabase.table("po_steps") \
        .select("*") \
        .eq("po_id", int(po_id)) \
        .order("step_index") \
        .execute().data

    return pd.DataFrame(data)

def go_back():
    """Reset to orders view and clear active PO."""
    st.session_state.view_mode = "orders"
    st.session_state.active_po_id = None
    st.session_state.active_po_number = None


def days_since(po_date_str):
    """Return number of days elapsed since PO date, or 0 if not parseable."""
    try:
        po_date = pd.to_datetime(po_date_str).date()
        return (date.today() - po_date).days
    except Exception:
        return 0


def is_overdue(row, threshold=25):
    """Return True if a PO is 'Not Started' and older than threshold days."""
    return (
        row["status"] == "Not Started"
        and days_since(row["po_date"]) >= threshold
    )

def build_full_context():
    """
    Fetches every product + every order + every step and returns a single
    structured string.  No filtering at all — Gemini decides what's relevant.
    """
    products = fetch_products()
    if products.empty:
        return "No data available."
 
    parts = []
    for _, p in products.iterrows():
        orders = fetch_orders(p["id"])
        if orders.empty:
            continue
        for _, row in orders.iterrows():
            steps = fetch_po_steps(int(row["id"]))
            done, pending = [], []
            if not steps.empty:
                for _, s in steps.iterrows():
                    desc   = s["step_description"]
                    remark = f" [{s['remark']}]" if s["remark"] else ""
                    if s["status"] == "Done":
                        done.append(f"  ✅ {desc}{remark}")
                    else:
                        pending.append(f"  ⏳ {desc}{remark}")
 
            parts.append(f"""Product: {p['product_name']}
PO: {row['po_number']}
Customer: {row['customer'] or 'N/A'}
Status: {row['status']}
Date: {row['po_date']}
Steps completed ({len(done)}):
{chr(10).join(done) if done else '  None'}
Steps remaining ({len(pending)}):
{chr(10).join(pending) if pending else '  All done'}
---""")
 
    return "\n".join(parts) if parts else "No data available."

def _render_order_cards(context, title="📋 <b>Orders</b>"):
    cards = []
    for block in context.split("---"):
        if "PO:" not in block:
            continue
        po = customer = status = po_date = product = ""
        for line in block.strip().splitlines():
            line = line.strip()
            if line.startswith("Product:"):  product  = line.split(":", 1)[1].strip()
            elif line.startswith("PO:"):     po       = line.split(":", 1)[1].strip()
            elif line.startswith("Customer:"):customer= line.split(":", 1)[1].strip()
            elif line.startswith("Status:"): status   = line.split(":", 1)[1].strip()
            elif line.startswith("Date:"):
                raw = line.split(":", 1)[1].strip()
                try:    po_date = pd.to_datetime(raw).strftime("%d %b %Y")
                except: po_date = raw
 
        color = {"Completed": "#16a34a", "Not Started": "#dc2626",
                 "In Progress": "#f59e0b"}.get(status, "#555")
        cards.append(f"""<div style="padding:8px 10px;border-radius:10px;margin:6px 0;background:#f1f5f9;">
📌 <b>{po}</b><br>
<span style='color:#2563eb;font-weight:600'>{product}</span><br>
<span style='color:#555'>{customer}</span><br>
<span style='color:{color};font-weight:600'>{status}</span><br>
<span style='color:#888'>📅 {po_date}</span>
</div>""")
 
    if not cards:
        return None
    return f"{title}<br>{''.join(cards)}"
def _render_step_cards(context):
    cards = []
    for block in context.split("---"):
        if "PO:" not in block:
            continue
        po = customer = product = status = ""
        done_lines, pending_lines = [], []
        section = None
        for line in block.strip().splitlines():
            line = line.strip()
            if line.startswith("Product:"):        product  = line.split(":", 1)[1].strip()
            elif line.startswith("PO:"):           po       = line.split(":", 1)[1].strip()
            elif line.startswith("Customer:"):     customer = line.split(":", 1)[1].strip()
            elif line.startswith("Status:"):       status   = line.split(":", 1)[1].strip()
            elif line.startswith("Steps completed"): section = "done"
            elif line.startswith("Steps remaining"): section = "pending"
            elif line.startswith("✅") and section == "done":
                done_lines.append(line.replace("✅", "").strip())
            elif line.startswith("⏳") and section == "pending":
                pending_lines.append(line.replace("⏳", "").strip())
 
        if not po:
            continue
 
        total = len(done_lines) + len(pending_lines)
        pct   = int(len(done_lines) / total * 100) if total else 0
 
        done_html    = "".join(f"<div style='padding:3px 0;color:#15803d;font-size:13px'>✅ {s}</div>" for s in done_lines) \
                       or "<div style='color:#888;font-size:13px'>None yet</div>"
        pending_html = "".join(f"<div style='padding:3px 0;color:#b45309;font-size:13px'>⏳ {s}</div>" for s in pending_lines) \
                       or "<div style='color:#15803d;font-size:13px'>All steps complete!</div>"
 
        cards.append(f"""
<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;margin:8px 0;">
  <div style="font-weight:600;font-size:14px;margin-bottom:2px;">📌 {po}</div>
  <div style="color:#2563eb;font-size:13px;font-weight:500;">{product}</div>
  <div style="color:#555;font-size:13px;">{customer}</div>
  <div style="margin:8px 0 4px;">
    <div style="background:#e2e8f0;border-radius:99px;height:6px;width:100%;">
      <div style="background:#16a34a;width:{pct}%;height:6px;border-radius:99px;"></div>
    </div>
    <div style="font-size:12px;color:#888;margin-top:3px;">{len(done_lines)}/{total} steps done ({pct}%)</div>
  </div>
  <details style="margin-top:8px;">
    <summary style="font-size:13px;font-weight:500;cursor:pointer;color:#374151;">Completed steps</summary>
    <div style="margin-top:6px;">{done_html}</div>
  </details>
  <details open style="margin-top:6px;">
    <summary style="font-size:13px;font-weight:500;cursor:pointer;color:#374151;">Remaining steps</summary>
    <div style="margin-top:6px;">{pending_html}</div>
  </details>
</div>""")
 
    return f"<b>🛠 Step Breakdown</b><br>{''.join(cards)}" if cards else None
  
_STEP_WORDS = {
    "step", "steps", "remaining", "pending step", "completed step",
    "which step", "what step", "how many step", "progress", "done step",
    "next step", "track", "stage", "stages", "current", "where is",
    "what is left", "what's left", "what remains", "how far",
}
 
_STATUS_WORDS = {
    "pending", "not started", "completed", "cancelled", "in progress",
}
 
_ANALYTICAL_WORDS = {
    "days", "since", "how long", "passed", "ago", "calculate",
    "difference", "priority", "why", "should", "recommend", "urgent",
    "analyse", "analyze", "suggest", "compare", "how many", "count", "total",
}
 
def _is_step_query(q): return any(w in q for w in _STEP_WORDS)
def _is_analytical(q): return any(w in q for w in _ANALYTICAL_WORDS)
def _is_simple_status(q): return any(w in q for w in _STATUS_WORDS) and not _is_analytical(q)
 
 
def _filter_context(full_context, q):
    """
    Best-effort filter: returns only the blocks relevant to the query.
    Falls back to the full context if nothing matches.
    """
    blocks = [b for b in full_context.split("---") if "PO:" in b]
    if not blocks:
        return full_context
 
    def norm(s):
        return re.sub(r"[\s\-_]+", "", s.lower())
 
    q_norm = norm(q)
    matched = []
 
    for block in blocks:
        # extract fields
        fields = {}
        for line in block.strip().splitlines():
            for key in ("Product", "PO", "Customer", "Status", "Date"):
                if line.strip().startswith(f"{key}:"):
                    fields[key] = line.split(":", 1)[1].strip().lower()
 
        # score how relevant this block is
        score = 0
        for field in fields.values():
            if norm(field) in q_norm or q_norm in norm(field):
                score += 2
            # word-level partial match
            for word in field.split():
                if len(word) > 3 and word in q:
                    score += 1
 
        if score > 0:
            matched.append((score, block))
 
    if not matched:
        return full_context          
 
    matched.sort(key=lambda x: -x[0])
    return "---\n".join(b for _, b in matched) + "\n---"
 

def chat_with_data(user_query, product_id=None):
    try:
        if time.time() - st.session_state.last_api_call < 2:
            return "⏳ Please wait a moment before sending another message."
 
        st.session_state.last_api_call = time.time()
 
        q = user_query.strip().lower()
 
        # ── Enrich follow-up queries with previously referenced context ──
        enriched = user_query
        has_ref = any(w in q for w in ["it", "this", "that", "the order", "the po"])
        if has_ref:
            if st.session_state.last_referenced_po:
                enriched += f" (referring to PO {st.session_state.last_referenced_po})"
            elif st.session_state.last_referenced_customer:
                enriched += f" (for customer {st.session_state.last_referenced_customer})"
            elif st.session_state.last_referenced_product:
                enriched += f" (for product {st.session_state.last_referenced_product})"
 
        full_context = build_full_context()

        filtered = _filter_context(full_context, enriched.lower())
 
        for block in filtered.split("---"):
            for line in block.strip().splitlines():
                line = line.strip()
                if line.startswith("PO:") and re.search(r'\b\d{2,}\b', line):
                    st.session_state.last_referenced_po = re.search(r'\d+', line).group()
                elif line.startswith("Customer:"):
                    val = line.split(":", 1)[1].strip()
                    if val and val.lower() != "n/a":
                        st.session_state.last_referenced_customer = val
                elif line.startswith("Product:"):
                    val = line.split(":", 1)[1].strip()
                    if val:
                        st.session_state.last_referenced_product = val
 
        if _is_step_query(q):
            result = _render_step_cards(filtered)
            if result:
                return result
 
        if _is_simple_status(q) and not _is_step_query(q):
            titles = {
                "not started": "📦 <b>Pending Orders</b>",
                "pending":     "📦 <b>Pending Orders</b>",
                "completed":   "✅ <b>Completed Orders</b>",
                "in progress": "🚧 <b>In Progress Orders</b>",
                "cancelled":   "❌ <b>Cancelled Orders</b>",
            }
            title = next((v for k, v in titles.items() if k in q), "📋 <b>Orders</b>")
            result = _render_order_cards(filtered, title)
            if result:
                return result
 
        history_text = ""
        if "chat_history" in st.session_state:
            recent = st.session_state.chat_history[-6:]
            for role, msg in recent:
                clean = re.sub(r"<[^>]+>", "", msg).strip()
                history_text += f"{role}: {clean}\n"
 
        prompt = f"""You are a smart business assistant for a manufacturing company.
Today's date: {date.today().strftime("%d %B %Y")}
 
Use ONLY the DATA below. Never invent information.
 
CONVERSATION HISTORY:
{history_text or "No previous messages"}
 
RESPONSE RULES:
- Answer every question, even general ones like "how are you" or "tell me about X"
- For order/customer/product queries: search the DATA and give a clear answer
- For counting: give the number first, then list items
- For date/time questions: calculate using today's date provided above
- For step/progress: summarise with X/Y done, list ✅ done and ⏳ remaining steps
- For follow-ups: use the conversation history to understand context
- For questions where nothing is found in DATA: say so clearly and helpfully
- Format each order block as:
  Product: [product name]  
  PO: [number]
  Customer: [name]
  Status: [status]
  Date: [date]
- Use ## for section headers if needed
 
DATA:
{full_context}
 
USER QUESTION: {enriched}
"""
 
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.1}
        )
        return response.text.strip()
 
    except Exception as e:
        import traceback
        return f"⚠️ Error: {traceback.format_exc()}"

def format_bot_reply(text):
    blocks = re.split(r'\n{2,}', text.strip())
    html_parts = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        if "Product:" in block and "PO:" in block and "Customer:" in block and "Status:" in block:
            lines = block.split("\n")
            po = customer = status = po_date = product = ""
            for line in lines:
                line = line.strip()
                if line.startswith("Product:"):   product  = line.split("Product:", 1)[1].strip()
                elif line.startswith("PO:"):       po       = line.split("PO:", 1)[1].strip()
                elif line.startswith("Customer:"): customer = line.split("Customer:", 1)[1].strip()
                elif line.startswith("Status:"):   status   = line.split("Status:", 1)[1].strip()
                elif line.startswith("Date:"):
                    raw = line.split("Date:", 1)[1].strip()
                    try:    po_date = pd.to_datetime(raw).strftime("%d %b %Y")
                    except: po_date = raw
            color = {"Completed": "#16a34a", "Not Started": "#dc2626", "In Progress": "#f59e0b"}.get(status, "#555")
            if po:
                html_parts.append(f"""<div style="background:#f1f5f9;border-radius:8px;padding:8px 10px;margin:5px 0;font-size:12px;">
  <div style="color:#2563eb;font-weight:600;font-size:13px">{product}</div>
  <div style="font-weight:600;color:#1e293b">📌 {po}</div>
  <div style="color:#555">👤 {customer}</div>
  <div style="color:{color};font-weight:500">● {status}</div>
  <div style="color:#888">📅 {po_date}</div>
</div>""")
                continue

        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
            if line.startswith("## "):
                html_parts.append(f"<div style='font-weight:600;font-size:13px;margin:10px 0 4px;color:#1e293b;border-bottom:1px solid #e2e8f0;padding-bottom:4px'>{line[3:]}</div>")
            elif line.startswith("# "):
                html_parts.append(f"<div style='font-weight:600;font-size:14px;margin:8px 0 4px;color:#1e293b'>{line[2:]}</div>")
            elif line.startswith("✅"):
                html_parts.append(f"<div style='padding:2px 0;color:#15803d;font-size:12px'>{line}</div>")
            elif line.startswith("⏳"):
                html_parts.append(f"<div style='padding:2px 0;color:#b45309;font-size:12px'>{line}</div>")
            elif line.startswith("- ") or line.startswith("* "):
                html_parts.append(f"<div style='padding:3px 0 3px 8px;font-size:12px;color:#374151;border-left:2px solid #e2e8f0;margin:2px 0'>• {line[2:]}</div>")
            else:
                html_parts.append(f"<div style='font-size:13px;margin:2px 0;color:#374151'>{line}</div>")

    inner = "".join(html_parts)
    return f"<div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;margin:6px 0;'>{inner}</div>"


    # Sidebar
st.sidebar.header("Mode")
st.session_state.mode = st.sidebar.radio("Select Mode", ["Operations", "Admin"])


#Admin Mode
if st.session_state.mode == "Admin":

    #Product Control 
    products = fetch_products(active_only=False)


    for _, row in products.iterrows():
        pid = int(row["id"])
        c1, c2, c3, c4, c5 = st.columns([3, 3, 1, 1, 1])

        name   = c1.text_input("Name",  row["product_name"], key=f"name_{pid}")
        sheet  = c2.text_input("Sheet", row["sheet_name"],   key=f"sheet_{pid}")
        active = c3.checkbox("Active",  bool(row["active"]), key=f"active_{pid}")

        if c4.button("Save", key=f"save_{pid}"):
            supabase.table("products") \
                .update({
                    "product_name": name.strip(),
                    "sheet_name": sheet.strip(),
                    "active": bool(active)
                }) \
                .eq("id", pid) \
                .execute()
            st.success("Updated")
            st.rerun()

        if c5.button("🗑", key=f"del_{pid}"):
            st.session_state.confirm_delete_pid = pid

    #Confirmation box before deleting anything 
    if st.session_state.confirm_delete_pid is not None:
        cpid  = st.session_state.confirm_delete_pid
        cname = products.loc[products["id"] == cpid, "product_name"].values
        label = cname[0] if len(cname) else f"ID {cpid}"
        st.warning(f"⚠️ Are you sure you want to delete **{label}**? This cannot be undone.")
        yes_col, no_col, _ = st.columns([1, 1, 6])
        if yes_col.button("✅ Yes, delete", key="confirm_yes"):
            supabase.table("products") \
                .delete() \
                .eq("id", cpid) \
                .execute()
            st.session_state.confirm_delete_pid = None
            st.toast(f"'{label}' deleted.", icon="🗑️")
            st.rerun()
        if no_col.button("❌ Cancel", key="confirm_no"):
            st.session_state.confirm_delete_pid = None
            st.rerun()

    st.divider()
    st.subheader("Want to add a new product? Follow the steps below")

    # Guide for first time user
    st.info("""

**1. Google Sheet Structure**
- First **3 rows** can be headers / notes (ignored)
- Actual steps must start from **row 4**
- Step description must be in **column C**

**2. Share the Sheet**
Share the Google Sheet with this **service account email** as **Editor**:

📧 **SERVICE ACCOUNT EMAIL**  

streamlit-sheets-bot@production-dashboard2.iam.gserviceaccount.com

*(This is a system account, not a personal Gmail)*

**3. Link Sheet to Product**
- Enter the **exact Google Sheet name**
- Click **Save**
- Steps will auto-load for every PO of this product

FYI - If the sheet name changes later, just update it here — no code changes needed.
""")

    st.divider()

    # Add new product 
    with st.form("add_product"):
        pname  = st.text_input("Product Name")
        sname  = st.text_input("Google Sheet Name")
        submit = st.form_submit_button("Add Product")

    if submit and pname.strip() and sname.strip():
        supabase.table("products").insert({
            "product_name": pname.strip(),
            "sheet_name": sname.strip(),
            "active": True
        }).execute()
        st.session_state.last_added_product = pname.strip()
        st.toast(f"Product '{pname.strip()}' added successfully!", icon="✅")
        st.rerun()


# Operations 
if st.session_state.mode == "Operations":

    products = fetch_products()
    if products.empty:
        st.warning("No active products")
        st.stop()

    product_names = products["product_name"].tolist()

    # Force-select a newly added product
    if st.session_state.last_added_product in product_names:
        st.session_state.selected_product   = st.session_state.last_added_product
        st.session_state.last_added_product = None

    # Fallback: if stored value no longer exists, reset to first
    if st.session_state.selected_product not in product_names:
        st.session_state.selected_product = product_names[0]

    st.sidebar.selectbox("Select Product", product_names, key="selected_product")
    st.sidebar.markdown("### 🤖 Assistant")

    if st.sidebar.button("Open Chat"):
            st.session_state.show_chat = not st.session_state.show_chat
    if st.session_state.show_chat:

        if "chat_history" not in st.session_state:
            st.session_state.chat_history = [("Bot", "Hi 👋 Ask me about your orders!")]

        # Show messages in sidebar
        for role, msg in st.session_state.chat_history:
            if role == "You":
                st.sidebar.markdown(
                    f"<div style='background:#dcf8c6;padding:6px;border-radius:8px;margin:4px;text-align:right'>{msg}</div>",
                    unsafe_allow_html=True
                )
            else:
                st.sidebar.markdown(
                    msg,
                    unsafe_allow_html=True
                )

        # Input in sidebar
        with st.sidebar.form("chat_form", clear_on_submit=True):
            user_input = st.text_input("Type message...")
            submitted = st.form_submit_button("Send")

        if submitted and user_input:

    # 🔒 prevent double trigger
            if st.session_state.is_processing:
                st.stop()

            st.session_state.is_processing = True
            st.session_state.last_query = user_input

            with st.sidebar:
                with st.spinner("🤖 typing..."):
                    reply = chat_with_data(user_input)

            st.session_state.chat_history.append(("You", user_input))
            if reply.startswith("<div") or reply.startswith("<b>"):
                st.session_state.chat_history.append(("Bot", reply))
            else:
                st.session_state.chat_history.append(("Bot", format_bot_reply(reply)))
            
            

            st.session_state.is_processing = False

            st.rerun()        
    selected   = st.session_state.selected_product
    product_df = products[products["product_name"] == selected]

    prev = st.session_state.get("_last_product")
    if prev is not None and prev != selected:
        go_back()
    st.session_state["_last_product"] = selected

    if product_df.empty:
        st.warning("Please select a product")
        st.stop()

    product    = product_df.iloc[0]
    product_id = int(product["id"])
    sheet_name = product["sheet_name"]

    

    # If the user switched product while in steps view, return to orders
    if st.session_state.view_mode == "steps" and st.session_state.active_po_id is not None:
        belongs = supabase.table("purchase_orders") \
            .select("id") \
            .eq("id", st.session_state.active_po_id) \
            .eq("product_id", product_id) \
            .execute().data
        if not belongs:
            go_back()

    # ================= BREADCRUMB & BACK NAVIGATION =================
    if st.session_state.view_mode == "steps":
        back_col, crumb_col = st.columns([1, 8])
        with crumb_col:
            st.markdown(f"**{product['product_name']}** › `{st.session_state.active_po_number or 'PO'}`")
        with back_col:
            if st.button("⬅ Back", use_container_width=True):
                go_back()
                st.rerun()
        st.divider()

    # Orders handling
    main_col = st.container()

    
    with main_col:
        if st.session_state.view_mode == "orders":

            st.subheader(f"📄 Orders – {product['product_name']}")
            orders = fetch_orders(product_id)
            
            if not orders.empty:
                # ── Overdue alert banner ──
                overdue_orders = orders[orders.apply(is_overdue, axis=1)]
                if not overdue_orders.empty:
                    po_list = ", ".join(f"**{r}**" for r in overdue_orders["po_number"].tolist())
                    count   = len(overdue_orders)
                    st.warning(
                        f"⚠️ {count} order(s) have **not been started** even after 25 days: {po_list}. "
                        "Please take action immediately.",
                        icon="🚨"
                    )

                # Column headers
                h1, h2, h3, h4, h5 = st.columns([2, 2, 1.5, 2, 0.5])
                h1.markdown("**PO Number**")
                h2.markdown("**Customer**")
                h3.markdown("**Date**")
                h4.markdown("**Status**")
                h5.markdown("**Del**")

                # One row per PO 
                for _, row in orders.iterrows():
                    po_id_row = int(row["id"])
                    age       = days_since(row["po_date"])
                    overdue   = row["status"] == "Not Started" and age >= 25

                    c1, c2, c3, c4, c5 = st.columns([2, 2, 1.5, 2, 0.5])

                    if overdue:
                        c1.markdown(
                            f'<div class="overdue-row">{row["po_number"]}</div>',
                            unsafe_allow_html=True
                        )
                    else:
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
                        supabase.table("purchase_orders") \
                            .update({"status": new_status}) \
                            .eq("id", po_id_row) \
                            .execute()

                    # Delete button 
                    if c5.button("🗑", key=f"del_po_{po_id_row}", help="Delete this PO"):
                        st.session_state.confirm_delete_po_id     = po_id_row
                        st.session_state.confirm_delete_po_number = row["po_number"]

                # PO deletion confirmation
                if st.session_state.confirm_delete_po_id is not None:
                    po_label = st.session_state.confirm_delete_po_number
                    st.warning(
                        f"⚠️ Delete PO **{po_label}**? "
                        "This will also remove all its steps. You can undo immediately after."
                    )
                    yes_col, no_col, _ = st.columns([1, 1, 6])
                    if yes_col.button("✅ Yes, delete", key="confirm_po_yes"):
                        del_id = st.session_state.confirm_delete_po_id
                        po_row = supabase.table("purchase_orders") \
                            .select("*") \
                            .eq("id", del_id) \
                            .execute().data

                        steps_rows = supabase.table("po_steps") \
                            .select("*") \
                            .eq("po_id", del_id) \
                            .order("step_index") \
                            .execute().data
                        
                        st.session_state.deleted_po_snapshot = {
                            "po":    po_row[0] if po_row else None,
                            "steps": steps_rows
                        }
                        supabase.table("po_steps") \
                            .delete() \
                            .eq("po_id", del_id) \
                            .execute()

                        supabase.table("purchase_orders") \
                            .delete() \
                            .eq("id", del_id) \
                            .execute()
                        st.session_state.confirm_delete_po_id     = None
                        st.session_state.confirm_delete_po_number = None
                        st.toast(f"PO '{po_label}' deleted. Click Undo to restore.", icon="🗑️")
                        st.rerun()
                    if no_col.button("❌ Cancel", key="confirm_po_no"):
                        st.session_state.confirm_delete_po_id     = None
                        st.session_state.confirm_delete_po_number = None
                        st.rerun()

                # Undo banner
                if st.session_state.deleted_po_snapshot is not None:
                    snap    = st.session_state.deleted_po_snapshot
                    po_data = snap["po"]
                    if po_data:
                        undo_label = po_data["po_number"]
                        st.info(f"🗑️ PO **{undo_label}** was deleted.")
                        undo_col, dismiss_col, _ = st.columns([1, 1, 6])
                        if undo_col.button("↩️ Undo", key="undo_po"):
                            supabase.table("purchase_orders").insert({
                            "po_number": po_data["po_number"],
                            "product_id": po_data["product_id"],
                            "customer": po_data["customer"],
                            "po_date": po_data["po_date"],
                            "status": po_data["status"]
                        }).execute()
                            new_po_id_row = supabase.table("purchase_orders") \
                            .select("id") \
                            .eq("po_number", po_data["po_number"]) \
                            .eq("product_id", po_data["product_id"]) \
                            .order("id", desc=True) \
                            .limit(1) \
                            .execute().data
                            if new_po_id_row:
                                new_po_id = new_po_id_row[0]["id"]
                                for s in snap["steps"]:
                                    supabase.table("po_steps").insert({
                                        "po_id": int(new_po_id),
                                        "step_index": s["step_index"],
                                        "step_description": s["step_description"],
                                        "status": s["status"],
                                        "remark": s["remark"],
                                        "updated_on": s["updated_on"]
                                    }).execute()
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
                existing = supabase.table("purchase_orders") \
                    .select("id") \
                    .eq("po_number", po.strip()) \
                    .eq("product_id", product_id) \
                    .execute().data
                if existing:
                    st.error(f"PO number **{po.strip()}** already exists for this product.")
                else:
                    supabase.table("purchase_orders").insert({
                        "po_number": po.strip(),
                        "product_id": int(product_id),
                        "customer": cust.strip(),
                        "po_date": po_date.isoformat(),
                        "status": status
                    }).execute()
                    st.toast(f"PO '{po.strip()}' added successfully!", icon="✅")
                    st.rerun()

    if st.session_state.view_mode == "steps":

        po_id = int(st.session_state.active_po_id)
        st.subheader("🛠 Steps")

        steps = fetch_po_steps(po_id)

        if steps.empty:
            raw = get_steps_raw(sheet_name)
            for i, step in enumerate(raw, start=1):
                supabase.table("po_steps").insert({
                    "po_id": int(po_id),
                    "step_index": int(i),
                    "step_description": step["description"],
                    "status": "Not Started"
                }).execute()
            steps = fetch_po_steps(po_id)

        display = pd.DataFrame({
            "Done": steps["status"] == "Done",
            "Date": steps.apply(
            lambda r: (
                pd.to_datetime(r["updated_on"], errors="coerce").strftime("%d/%m/%y")
                if pd.notna(r["updated_on"]) else ""
            ),
            axis=1
        ),
            "Description": steps["step_description"],
            "Remark":      steps["remark"].fillna("")
        })

        edited = st.data_editor(
            display,
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
                supabase.table("po_steps") \
                    .update({
                        "step_description": ed["Description"],
                        "status": new_status,
                        "remark": ed["Remark"],
                        "updated_on": new_date
                    }) \
                    .eq("id", int(row["id"])) \
                    .execute()
                if new_done != was_done:
                    needs_rerun = True

        if needs_rerun:
            st.rerun()

        # Add a custom step row 
        st.divider()
        with st.form("add_step"):
            new_desc = st.text_input("Step Description", placeholder="Enter new step...")
            new_rmk  = st.text_input("Remark (optional)")
            add_step = st.form_submit_button("➕ Add Step")

        if add_step and new_desc.strip():
            next_idx = int(steps["step_index"].max()) + 1 if not steps.empty else 1
            supabase.table("po_steps").insert({
                "po_id": int(po_id),
                "step_index": int(next_idx),
                "step_description": new_desc.strip(),
                "status": "Not Started",
                "remark": new_rmk.strip() or None
            }).execute()
            st.toast("Step added.", icon="✅")
            st.rerun()

