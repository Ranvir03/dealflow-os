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
    return pd.read_sql_query("SELECT * FROM deals ORDER BY id DESC", conn)

df = load_data()

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

def explain_score(growth, ebitda):
    return f"Growth: {growth}%, EBITDA: {ebitda} → Investment requires further diligence."

def open_deal(deal_id):
    st.session_state.deal_id = deal_id
    st.session_state.page = "Deal Workspace"
    st.rerun()

# =====================================================
# SIDEBAR NAV
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

        col1, col2 = st.columns(2)

        with col1:
            company = st.text_input("Company Name")
            sector = st.selectbox(
                "Sector",
                ["Technology","Healthcare","Industrials","Energy","Consumer","Financial Services"]
            )
            ebitda = st.number_input("EBITDA ($M)", min_value=1.0, value=25.0)
            revenue = st.number_input("Revenue ($M)", min_value=1.0, value=100.0)

        with col2:
            growth = st.slider("Growth (%)", -10.0, 100.0, 12.0)
            size = st.number_input("Enterprise Value ($M)", min_value=10.0, value=250.0)
            entry_multiple = st.slider("Entry Multiple (x)", 1.0, 25.0, 8.0)
            ownership = st.slider("Ownership (%)", 10, 100, 100)

        owner = st.selectbox("Owner", ["Analyst","VP","Partner"])
        notes = st.text_area("Notes / Investment Thesis")

        submitted = st.form_submit_button("Add Deal")

        if submitted:

            if company.strip() == "":
                st.error("Company required")
                st.stop()

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
            st.success("Deal added successfully")
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

    deal_id = st.session_state.deal_id

    if not deal_id:
        st.warning("Select a deal first")
        st.stop()

    deal_df = df[df["id"] == deal_id]

    if deal_df.empty:
        st.warning("Deal not found")
        st.stop()

    deal = deal_df.iloc[0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Company", deal["company"])
    col2.metric("Score", deal["score"])
    col3.metric("Stage", deal["stage"])
    col4.metric("Priority", deal["priority"])

    st.divider()

    st.subheader("Financials")

    st.write({
        "EBITDA": deal["ebitda"],
        "Revenue": deal["revenue"],
        "Growth": deal["growth"],
        "EV": deal["size"]
    })

    st.divider()

    st.subheader("Decision")

df_current = load_data()
deal = df_current[df_current["id"] == deal_id].iloc[0]

current = deal["decision"] if deal["decision"] else "Pending"

decision = st.selectbox(
    "Decision",
    ["Pending","Approve","Reject","Hold"],
    index=["Pending","Approve","Reject","Hold"].index(current)
)

reason = st.text_area(
    "Rationale",
    value=deal["decision_reason"] if deal["decision_reason"] else ""
)

if st.button("Save Decision"):

    c.execute("""
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

    st.success("Decision saved")
    st.rerun()

    st.divider()

    st.subheader("Insight")
    st.write(explain_score(deal["growth"], deal["ebitda"]))

    st.divider()

    st.subheader("Delete Deal")

    confirm = st.checkbox("Confirm delete")

    if confirm:
        if st.button("Delete Deal"):

            c.execute("DELETE FROM deals WHERE id=?", (deal["id"],))
            conn.commit()

            st.session_state.deal_id = None
            st.session_state.page = "Pipeline"

            st.success("Deleted")
            st.rerun()

# =====================================================
# DECISION CENTER
# =====================================================
elif page == "Decision Center":

    st.header("Decision Center")

    # 🔥 ALWAYS reload fresh DB state
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
        st.info("No decisions yet.")
    else:
        st.dataframe(final, use_container_width=True)