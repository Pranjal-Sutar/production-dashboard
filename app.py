#last edited 20/4/26
import streamlit as st
import pandas as pd
from datetime import date, datetime
from db import get_connection
from supabase_client import supabase
from sheets import get_steps_raw
from dotenv import load_dotenv
load_dotenv()
import time
# ================= CONFIG =================
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
st.session_state.setdefault("last_api_call", 0)
st.session_state.setdefault("last_query", "")
st.session_state.setdefault("last_referenced_po", None)
st.session_state.setdefault("last_referenced_product", None)
st.session_state.setdefault("last_referenced_customer", None)
st.session_state.setdefault("is_processing", False)
# ================= HELPERS =================
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

def format_bot_reply(text):
    import re

    # detect PO blocks and convert them to styled cards
    def render_po_block(block):
        lines = block.strip().split("\n")
        po, customer, status, date = "", "", "", ""
        for line in lines:
            line = line.strip()
            if line.startswith("PO:"):
                po = line.split("PO:")[1].strip()
            elif line.startswith("Customer:"):
                customer = line.split("Customer:")[1].strip()
            elif line.startswith("Status:"):
                status = line.split("Status:")[1].strip()
            elif line.startswith("Date:"):
                raw = line.split("Date:")[1].strip()
                try:
                    date = pd.to_datetime(raw).strftime("%d %b %Y")
                except:
                    date = raw

        if not po:
            return None

        if status == "Completed":
            color = "#16a34a"
        elif status == "Not Started":
            color = "#dc2626"
        elif status == "In Progress":
            color = "#f59e0b"
        else:
            color = "#555"

        return f"""<div style="background:#f1f5f9;border-radius:8px;padding:8px 10px;margin:5px 0;font-size:12px;">
  <div style="font-weight:600;color:#1e293b">📌 {po}</div>
  <div style="color:#555">👤 {customer}</div>
  <div style="color:{color};font-weight:500">● {status}</div>
  <div style="color:#888">📅 {date}</div>
</div>"""

    # split text into PO blocks and non-PO text
    # a PO block is any group of lines containing PO: Customer: Status: Date:
    blocks = re.split(r'\n{2,}', text.strip())
    html_parts = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # check if this looks like a PO block
        if "PO:" in block and "Customer:" in block and "Status:" in block:
            card = render_po_block(block)
            if card:
                html_parts.append(card)
                continue

        # otherwise render line by line
        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("## "):
                html_parts.append(f"<div style='font-weight:600;font-size:13px;margin:10px 0 4px;color:#1e293b;border-bottom:1px solid #e2e8f0;padding-bottom:4px'>{line[3:]}</div>")
            elif line.startswith("# "):
                html_parts.append(f"<div style='font-weight:600;font-size:14px;margin:8px 0 4px;color:#1e293b'>{line[2:]}</div>")
            elif line.startswith("✅"):
                line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
                html_parts.append(f"<div style='padding:2px 0;color:#15803d;font-size:12px'>{line}</div>")
            elif line.startswith("⏳"):
                line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
                html_parts.append(f"<div style='padding:2px 0;color:#b45309;font-size:12px'>{line}</div>")
            elif line.startswith("- ") or line.startswith("* "):
                content = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line[2:])
                html_parts.append(f"<div style='padding:3px 0 3px 8px;font-size:12px;color:#374151;border-left:2px solid #e2e8f0;margin:2px 0'>• {content}</div>")
            elif line.startswith("**") and line.endswith("**"):
                html_parts.append(f"<div style='font-weight:600;font-size:13px;margin:6px 0 2px'>{line[2:-2]}</div>")
            else:
                line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
                html_parts.append(f"<div style='font-size:13px;margin:2px 0;color:#374151'>{line}</div>")

    inner = "".join(html_parts)
    return f"""<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;margin:6px 0;">
{inner}
</div>"""



def build_context_all(query=None):
    products = fetch_products()
    context = ""
    all_orders = pd.DataFrame()

    q = query.lower() if query else ""

    # ================= STEP 1: COLLECT ALL ORDERS =================
    for _, p in products.iterrows():
        orders = fetch_orders(p["id"])

        if orders.empty:
            continue

        orders["product_name"] = p["product_name"]
        all_orders = pd.concat([all_orders, orders], ignore_index=True)

    # ================= STEP 2: APPLY FILTERS =================
    orders = all_orders

    if orders.empty:
        return "No relevant data found"

    # -------- STATUS FILTER --------
    if any(word in q for word in ["pending", "not started", "not done"]):
        orders = orders[orders["status"] == "Not Started"]

    elif any(word in q for word in ["completed", "done", "finished"]):
        orders = orders[orders["status"] == "Completed"]

    elif "cancelled" in q:
        orders = orders[orders["status"] == "Cancelled"]

    elif "in progress" in q:
        orders = orders[orders["status"] == "In Progress"]

    # -------- CUSTOMER FILTER --------
    for _, row in orders.iterrows():
        if row["customer"] and row["customer"].lower() in q:
            orders = orders[orders["customer"].str.lower() == row["customer"].lower()]
            break

    # -------- DATE FILTER --------
    if any(word in q for word in ["recent", "latest", "last"]):
        orders = orders.sort_values(by="po_date", ascending=False).head(1)

    if "first" in q or "oldest" in q:
        orders = orders.sort_values(by="po_date", ascending=True).head(1)

    # -------- MONTH FILTER --------
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12
    }

    for month_name, month_num in months.items():
        if month_name in q:
            orders["po_date"] = pd.to_datetime(orders["po_date"], errors="coerce")
            orders = orders[orders["po_date"].dt.month == month_num]
            break

    if orders.empty:
        return "No relevant data found"

    # ================= STEP 3: BUILD CONTEXT =================
    for _, row in orders.iterrows():
        context += f"""
Product: {row['product_name']}
PO: {row['po_number']}
Customer: {row['customer']}
Status: {row['status']}
Date: {row['po_date']}
---
"""

    return context

def build_context_with_steps(query=None):
    products = fetch_products()
    context = ""
    all_rows = []
    q = query.lower() if query else ""

    for _, p in products.iterrows():
        orders = fetch_orders(p["id"])
        if orders.empty:
            continue
        for _, row in orders.iterrows():
            all_rows.append((p, row))

    if not all_rows:
        return build_context_all(query)
        
    # status filter
    if any(word in q for word in ["pending", "not started", "not done"]):
        all_rows = [(p, r) for p, r in all_rows if r["status"] == "Not Started"]
    elif any(word in q for word in ["completed", "done", "finished"]):
        all_rows = [(p, r) for p, r in all_rows if r["status"] == "Completed"]
    elif "cancelled" in q:
        all_rows = [(p, r) for p, r in all_rows if r["status"] == "Cancelled"]
    elif "in progress" in q:
        all_rows = [(p, r) for p, r in all_rows if r["status"] == "In Progress"]

    # customer filter
    for p, row in all_rows:
        if row["customer"] and row["customer"].lower() in q:
            all_rows = [(p, r) for p, r in all_rows if r["customer"] and r["customer"].lower() == row["customer"].lower()]
            break

    # product filter

    # -------- PRODUCT FILTER --------

    products_df = fetch_products()
    product_names = [p.lower() for p in products_df["product_name"].tolist()]
    
    matched_product = None
    
    for pname in product_names:
        words = pname.split()
        
        # match if ANY word appears in query
        if any(word in q for word in words):
            matched_product = pname
            break
    
    if matched_product:
        all_rows = [
            (p, r) for p, r in all_rows
            if p["product_name"].lower() == matched_product
        ]
        
    # date filters
    if any(word in q for word in ["recent", "latest", "last"]):
        all_rows = sorted(all_rows, key=lambda x: x[1]["po_date"], reverse=True)[:1]
    elif "first" in q or "oldest" in q:
        all_rows = sorted(all_rows, key=lambda x: x[1]["po_date"])[:1]

    # month filter
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12
    }
    for month_name, month_num in months.items():
        if month_name in q:
            all_rows = [
                (p, r) for p, r in all_rows
                if pd.to_datetime(r["po_date"], errors="coerce").month == month_num
            ]
            break

    if not all_rows:
        return "No relevant data found"

    for p, row in all_rows:
        steps = fetch_po_steps(int(row["id"]))
        done_steps, pending_steps = [], []

        if not steps.empty:
            for _, s in steps.iterrows():
                desc = s["step_description"]
                remark = s["remark"] or ""
                if s["status"] == "Done":
                    done_steps.append(f"  ✅ {desc}" + (f" [{remark}]" if remark else ""))
                else:
                    pending_steps.append(f"  ⏳ {desc}" + (f" [{remark}]" if remark else ""))

        context += f"""
Product: {p['product_name']}
PO: {row['po_number']}
Customer: {row['customer']}
Status: {row['status']}
Date: {row['po_date']}
Steps completed ({len(done_steps)}):
{chr(10).join(done_steps) if done_steps else "  None"}
Steps remaining ({len(pending_steps)}):
{chr(10).join(pending_steps) if pending_steps else "  All done"}
---
"""

    return context

def is_step_query(query):
    q = query.lower()
    keywords = [
        "step", "steps", "remaining", "pending step", "completed step",
        "which step", "what step", "how many step", "progress",
        "done step", "next step", "track", "stage", "stages",
        "going", "current", "happening", "where is", "what is left",
        "what's left", "what remains", "how far", "how complete",
        "chal raha", "kya hua", "kitna"
    ]
    return any(word in q for word in keywords)


def format_steps_response(context, query):
    import re
    blocks = context.split("---")
    result = []

    # extract PO number or customer name from query for filtering
    po_match = re.search(r'\b(\d{2,})\b', query)
    po_filter = po_match.group(1) if po_match else None

    # extract customer name filter
    customer_filter = None
    q = query.lower()

    for block in blocks:
        if "PO:" not in block:
            continue

        po, product, customer, status = "", "", "", ""
        done_lines, pending_lines = [], []
        section = None

        for line in block.strip().split("\n"):
            line = line.strip()
            if line.startswith("Product:"):
                product = line.split("Product:")[1].strip()
            elif line.startswith("PO:"):
                po = line.split("PO:")[1].strip()
            elif line.startswith("Customer:"):
                customer = line.split("Customer:")[1].strip()
            elif line.startswith("Status:"):
                status = line.split("Status:")[1].strip()
            elif line.startswith("Steps completed"):
                section = "done"
            elif line.startswith("Steps remaining"):
                section = "pending"
            elif line.startswith("✅") and section == "done":
                done_lines.append(line.replace("✅", "").strip())
            elif line.startswith("⏳") and section == "pending":
                pending_lines.append(line.replace("⏳", "").strip())

        if not po:
            continue

        # filter by PO number if mentioned
        if po_filter and po.strip() != po_filter.strip():
            continue

        # filter by customer if mentioned
        if customer and customer.lower() in q:
            pass  # keep this block
        elif po_filter is None and customer and customer.lower() not in q:
            # check if any customer name in query matches
            pass  # let build_context_with_steps handle filtering

        done_html = "".join(
            f"<div style='padding:3px 0;color:#15803d;font-size:13px'>✅ {s}</div>"
            for s in done_lines
        ) or "<div style='color:#888;font-size:13px'>None yet</div>"

        pending_html = "".join(
            f"<div style='padding:3px 0;color:#b45309;font-size:13px'>⏳ {s}</div>"
            for s in pending_lines
        ) or "<div style='color:#15803d;font-size:13px'>All steps complete!</div>"

        total = len(done_lines) + len(pending_lines)
        pct = int((len(done_lines) / total * 100)) if total else 0

        result.append(f"""
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

    if not result:
        return "No step data found."

    return f"<b>🛠 Step Breakdown</b><br>{''.join(result)}"

def is_simple_query(query):
    q = query.lower()
    keywords = [
        "pending", "not started", "completed",
        "cancelled", "in progress",
        "customer", "old", "recent",
        "last", "latest", "first",
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december"
    ]
    # exclude analytical/calculation queries — let Gemini handle these
    bypass_words = [
        "days", "since", "how long", "passed", "ago", "calculate", "difference",
        "todays date", "priority", "why", "which", "should", "recommend",
        "important", "urgent", "analyse", "analyze", "suggest", "compare",
        "what do you think", "how many", "count", "total"
    ]
    if any(word in q for word in bypass_words):
        return False
    return any(word in q for word in keywords)
    
def format_orders(context, query):
    lines = context.split("---")
    result = []

    for item in lines:
        if "PO:" in item:
            po = ""
            customer = ""
            status = ""
            date = ""
            product = ""

            for line in item.split("\n"):
                if "Product:" in line:
                    product = line.split("Product:")[1].strip()

                if "PO:" in line:
                    po = line.split("PO:")[1].strip()

                if "Customer:" in line:
                    customer = line.split("Customer:")[1].strip()

                if "Status:" in line:
                    status = line.split("Status:")[1].strip()

                if "Date:" in line:
                    raw_date = line.split("Date:")[1].strip()
                    try:
                        date = pd.to_datetime(raw_date).strftime("%d %b %Y")
                    except:
                        date = raw_date

            # 🎨 status colors
            if status == "Completed":
                color = "#16a34a"
            elif status == "Not Started":
                color = "#dc2626"
            elif status == "In Progress":
                color = "#f59e0b"
            else:
                color = "#555"

            result.append(
                f"""<div style="padding:8px 10px;border-radius:10px;margin:6px 0;background:#f1f5f9;">
📌 <b>{po}</b><br>
<span style='color:#2563eb; font-weight:600'>{product}</span><br>
<span style='color:#555'>{customer}</span><br>
<span style='color:{color}; font-weight:600'>{status}</span><br>
<span style='color:#888'>📅 {date}</span>
</div>"""
            )

    if not result:
        return "Not available in system data"

    q = query.lower()

    if "pending" in q or "not started" in q:
        title = "📦 <b>Pending Orders</b>"
    elif "completed" in q:
        title = "✅ <b>Completed Orders</b>"
    elif "progress" in q:
        title = "🚧 <b>In Progress Orders</b>"
    elif any(word in q for word in ["latest", "last"]):
        title = "🆕 <b>Latest Order</b>"
    elif any(m in q for m in [
        "january","february","march","april","may","june",
        "july","august","september","october","november","december"
    ]):
        title = "📅 <b>Orders by Month</b>"
    else:
        title = "📋 <b>Orders</b>"

    return f"{title}<br>{''.join(result)}"

def chat_with_data(user_query, product_id=None):
    try:
        import time
        import re

        q = user_query.strip().lower()

        if time.time() - st.session_state.last_api_call < 3:
            return "⏳ Please wait a moment..."

        st.session_state.last_api_call = time.time()

        # ── Detect what's in the query FIRST ──
        po_match = re.search(r'\b(\d{2,})\b', q)
        has_po = po_match is not None
        has_product = any(p.lower() in q for p in fetch_products()["product_name"].tolist())
        broadening_words = ["other", "more", "else", "all", "any", "list", "how many", "total", "rest", "another"]
        is_broadening = any(word in q for word in broadening_words)

    
        # ── Enrich query with last referenced context for follow-ups ──
        enriched_query = user_query

        if not has_po and not has_product and not is_broadening:
            if st.session_state.last_referenced_po:
                enriched_query = f"{user_query} for PO {st.session_state.last_referenced_po}"
            elif st.session_state.last_referenced_customer:
                enriched_query = f"{user_query} for {st.session_state.last_referenced_customer}"
            elif st.session_state.last_referenced_product:
                enriched_query = f"{user_query} for {st.session_state.last_referenced_product}"
        elif is_broadening and st.session_state.last_referenced_customer:
            enriched_query = f"{user_query} for customer {st.session_state.last_referenced_customer}"

        # ── Build context ──
        context = build_context_with_steps(enriched_query)

        # ── Save references for future follow-ups ──
        if has_po:
            st.session_state.last_referenced_po = po_match.group(1)
        if has_product:
            for pname in fetch_products()["product_name"].tolist():
                if pname.lower() in q:
                    st.session_state.last_referenced_product = pname
                    break

        # save customer from context
        if context != "No relevant data found":
            for block in context.split("---"):
                for line in block.split("\n"):
                    if line.strip().startswith("Customer:"):
                        cust_val = line.split("Customer:")[1].strip()
                        if cust_val:
                            st.session_state.last_referenced_customer = cust_val
                        break

        # Fast path 1 — simple order queries, no API
        if is_simple_query(enriched_query) and not is_step_query(enriched_query):
            return format_orders(context, enriched_query)

        # Fast path 2 — step queries, render as cards, no API
        if is_step_query(enriched_query):
            formatted = format_steps_response(context, enriched_query)
            if formatted and formatted != "No step data found.":
                return formatted

        # Gemini for everything else
        history_text = ""
        if "chat_history" in st.session_state and len(st.session_state.chat_history) > 1:
            recent = st.session_state.chat_history[-6:]
            for role, msg in recent:
                clean_msg = re.sub(r'<[^>]+>', '', msg).strip()
                history_text += f"{role}: {clean_msg}\n"

        prompt = f"""You are a helpful business assistant for a manufacturing company.
Today's date is: {date.today().strftime("%d %B %Y")}

ONLY use the DATA below. Do not assume or invent anything outside it.

CONVERSATION HISTORY (for context on follow-up questions):
{history_text if history_text else "No previous messages"}

RESPONSE RULES:
- For order status questions: mention PO number, customer, status, date
- For counting questions like "how many orders": give the count first, then list each order
- When listing multiple orders, put EACH order as its own block with a blank line between them
- Format each order exactly like this (one field per line, no commas):
  PO: [number]
  Customer: [name]
  Status: [status]
  Date: [date]
- For date/time questions like "how many days since order":
    * Use today's date provided above
    * Calculate the difference yourself and state it clearly
- For step/progress questions:
    * Show X/Y steps done (Z%) summary
    * COMPLETED STEPS — one step per line starting with ✅
    * REMAINING STEPS — one step per line starting with ⏳
    * Each step on its own line, never in a paragraph
- If asked "which step is going" or "current step" → show the last ✅ step and next ⏳ step only
- For follow-up questions → use the PO from conversation history
- Use ## for section headers
- Do NOT use **bold** markdown for field labels
- If nothing relevant found in DATA, say "This order was not found in the system"

DATA:
{context}

QUESTION:
{user_query}
"""



        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.1}
        )

        st.session_state.last_query = q
        return response.text.strip()

    except Exception as e:
        import traceback
        return f"⚠️ Error: {traceback.format_exc()}"        

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

    # ── Confirmation dialog rendered outside the column loop ──
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

    # ---------- GUIDE ----------
    st.info("""

**1️⃣ Google Sheet Structure**
- First **3 rows** can be headers / notes (ignored)
- Actual steps must start from **row 4**
- Step description must be in **column C**

**2️⃣ Share the Sheet**
Share the Google Sheet with this **service account email** as **Editor**:

📧 **SERVICE ACCOUNT EMAIL**  


*(This is a system account, not a personal Gmail)*
t
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
        supabase.table("products").insert({
            "product_name": pname.strip(),
            "sheet_name": sname.strip(),
            "active": True
        }).execute()
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

            # only apply format_bot_reply to Gemini text responses, not already-HTML fast path responses
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

    

    # ── If the user switched product while in steps view, return to orders ──
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

    # ================= ORDERS =================
    main_col = st.container()

    
    with main_col:
        if st.session_state.view_mode == "orders":

            st.subheader(f"📄 Orders – {product['product_name']}")
            orders = fetch_orders(product_id)
            
            if not orders.empty:

                # ── Inject CSS once: .row-highlight wraps each overdue row ──
                

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
                    age       = days_since(row["po_date"])
                    overdue   = row["status"] == "Not Started" and age >= 25

                    c1, c2, c3, c4, c5 = st.columns([2, 2, 1.5, 2, 0.5])

                    # Inject an invisible tagged div into c1 so CSS can target the parent row
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

                    # ── Delete button ──
                    if c5.button("🗑", key=f"del_po_{po_id_row}", help="Delete this PO"):
                        st.session_state.confirm_delete_po_id     = po_id_row
                        st.session_state.confirm_delete_po_number = row["po_number"]

                # ── PO deletion confirmation banner ──
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

                # ── Undo banner ──
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

        # ── Add a custom step row ──
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

