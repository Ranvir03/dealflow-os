import streamlit as st
import pandas as pd
import sqlite3
import datetime
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# =====================================================
# CONFIG
# =====================================================
st.set_page_config(page_title="DealFlow OS", layout="wide")

# =====================================================
# SESSION STATE
# =====================================================
if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

if "deal_id" not in st.session_state:
    st.session_state.deal_id = None

# =====================================================
# UI
# =====================================================
st.title("🚀 DealFlow OS")
st.caption("VP-Level Investment Decision System")

# =====================================================
# DB
# =====================================================
conn = sqlite3.connect("deals.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
c = conn.cursor()

def init_db():
    c.execute("""
    CREATE TABLE IF NOT EXISTS deals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        company TEXT,
        sector TEXT,
        ebitda REAL,
        revenue REAL,
        growth REAL,
        size REAL,
        entry_multiple REAL,
        ownership REAL,
        score REAL,
        priority TEXT,
        stage TEXT,
        owner TEXT,
        notes TEXT,
        decision TEXT,
        decision_reason TEXT,
        decision_date TEXT
    )
    """)
    conn.commit()

init_db()

def load_data():
    conn = sqlite3.connect("deals.db", check_same_thread=False)
    df = pd.read_sql_query("SELECT * FROM deals ORDER BY id DESC", conn)
    conn.close()
    return df

# =====================================================
# HELPERS
# =====================================================
def priority(score):
    if score >= 10:
        return "🔥 Must Review"
    elif score >= 7:
        return "🟡 High Priority"
    return "🔵 Watchlist"

stages = ["SOURCED", "SCREENED", "IC", "APPROVED", "CLOSED"]

def next_stage(current):
    if current not in stages:
        return "SOURCED"
    return stages[min(stages.index(current) + 1, len(stages)-1)]

def open_deal(deal_id):
    st.session_state.deal_id = deal_id
    st.session_state.page = "Deal Workspace"
    st.rerun()

# =====================================================
# ROLE SYSTEM
# =====================================================
role = st.sidebar.selectbox("Role", ["Analyst","VP","Partner","Executive"])

permissions = {
    "Analyst": ["Dashboard","Deal Intake","Pipeline","Deal Workspace"],
    "VP": ["Dashboard","Deal Intake","Pipeline","Deal Workspace","Decision Center"],
    "Partner": ["Dashboard","Pipeline","Deal Workspace","Decision Center"],
    "Executive": ["Dashboard","Pipeline","Decision Center"]
}

pages = permissions[role]

if st.session_state.page not in pages:
    st.session_state.page = pages[0]

page = st.sidebar.radio("Navigation", pages)
st.session_state.page = page

st.sidebar.markdown("---")
st.sidebar.info(f"{role}")

# =====================================================
# LOAD DATA (NEVER GLOBAL CACHED FOR LOGIC)
# =====================================================
df = load_data()

# =====================================================
# DASHBOARD
# =====================================================
if page == "Dashboard":

    st.header("Executive Overview")

    for _, r in df.iterrows():

        col1, col2 = st.columns([4,1])

        with col1:
            st.write(f"**{r['company']}** | Score: {r['score']} | {r['stage']}")

        with col2:
            if st.button("Open", key=f"d_{r['id']}"):
                open_deal(r["id"])

# =====================================================
# DEAL INTAKE
# =====================================================
elif page == "Deal Intake":

    st.header("📥 Deal Intake")

    with st.form("deal_form"):

        company = st.text_input("Company")
        sector = st.selectbox("Sector", ["Tech","Healthcare","Industrials","Energy","Consumer"])

        ebitda = st.number_input("EBITDA", 1.0)
        revenue = st.number_input("Revenue", 1.0)
        growth = st.slider("Growth %", -10.0, 100.0, 10.0)
        size = st.number_input("EV", 10.0)
        entry_multiple = st.slider("Entry Multiple", 1.0, 25.0, 8.0)
        ownership = st.slider("Ownership %", 10, 100, 100)
        owner = st.selectbox("Owner", ["Analyst","VP","Partner"])
        notes = st.text_area("Notes")

        submitted = st.form_submit_button("Add Deal")

        if submitted:

            score = round((growth * 0.35) + (ebitda * 0.25), 2)

            c.execute("""
            INSERT INTO deals (
                date, company, sector, ebitda, revenue, growth,
                size, entry_multiple, ownership, score,
                priority, stage, owner, notes, decision
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                str(datetime.date.today()),
                company,
                sector,
                ebitda,
                revenue,
                growth,
                size,
                entry_multiple,
                ownership,
                score,
                priority(score),
                "SOURCED",
                owner,
                notes,
                "Pending"
            ))

            conn.commit()
            st.success("Deal added")
            st.rerun()

# =====================================================
# PIPELINE
# =====================================================
elif page == "Pipeline":

    st.header("Pipeline")

    for _, r in df.iterrows():

        col1, col2 = st.columns([4,1])

        with col1:
            st.write(f"**{r['company']}** | {r['score']} | {r['stage']}")

        with col2:
            if st.button("Open", key=f"p_{r['id']}"):
                open_deal(r["id"])

# =====================================================
# DEAL WORKSPACE
# =====================================================
elif page == "Deal Workspace":

    st.header("🧠 Deal Cockpit")

    deal_id = st.session_state.get("deal_id")

    if not deal_id:
        st.warning("Select a deal")
        st.stop()

    df_live = load_data()
    deal_row = df_live[df_live["id"] == deal_id]

    if deal_row.empty:
        st.warning("Deal not found")
        st.stop()

    deal = deal_row.iloc[0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Company", deal["company"])
    col2.metric("Score", deal["score"])
    col3.metric("Stage", deal["stage"])
    col4.metric("Priority", deal["priority"])

    st.divider()

    st.subheader("Decision")

    current = deal["decision"] if deal["decision"] else "Pending"

    decision = st.selectbox(
        "Decision",
        ["Pending","Approve","Reject","Hold"],
        index=["Pending","Approve","Reject","Hold"].index(current)
    )

    reason = st.text_area("Rationale", value=deal["decision_reason"] or "")

if st.button("Save Decision"):

    conn.execute("""
    UPDATE deals
    SET decision=?, decision_reason=?, decision_date=?
    WHERE id=?
    """, (
        decision,
        reason,
        str(datetime.date.today()),
        deal["id"]
    ))

    conn.commit()

    # 🔥 force refresh + redirect to Decision Center
    st.session_state.page = "Decision Center"
    st.session_state.deal_id = deal["id"]

    st.rerun()

    st.divider()

    st.subheader("Insight")
    st.write(f"Growth {deal['growth']}%, EBITDA {deal['ebitda']}")

    # =====================================================
    # DELETE (ROLE-BASED)
    # =====================================================
    st.divider()
    st.subheader("🗑 Danger Zone")

    if role in ["VP","Partner","Executive"]:

        confirm = st.checkbox("Confirm delete")

        if confirm:
            if st.button("Delete Deal"):

                c.execute("DELETE FROM deals WHERE id=?", (deal["id"],))
                conn.commit()

                st.session_state.deal_id = None
                st.session_state.page = "Pipeline"

                st.success("Deal deleted")
                st.rerun()

    else:
        st.info("You do not have permission to delete deals")

# =====================================================
# DECISION CENTER
# =====================================================
elif page == "Decision Center":

    st.header("Decision Center")

    df_live = load_data()

    approved = df_live[df_live["decision"] == "Approve"]
    rejected = df_live[df_live["decision"] == "Reject"]
    hold = df_live[df_live["decision"] == "Hold"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Approved", len(approved))
    c2.metric("Rejected", len(rejected))
    c3.metric("Hold", len(hold))

    st.divider()

    final = df_live[df_live["decision"].isin(["Approve","Reject","Hold"])]

    if final.empty:
        st.info("No decisions yet")
    else:
        st.dataframe(final, use_container_width=True)