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
st.set_page_config(page_title="DealFlow OS v2", layout="wide")

st.title("🚀 DealFlow OS v2")
st.caption("Institutional Deal Management System")

# =====================================================
# SESSION STATE
# =====================================================
if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

if "deal_id" not in st.session_state:
    st.session_state.deal_id = None

# =====================================================
# DB CONNECTION
# =====================================================
conn = sqlite3.connect("deals.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# =====================================================
# DATABASE (EXPANDED SCHEMA)
# =====================================================
def init_db():
    c.execute("""
    CREATE TABLE IF NOT EXISTS deals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        company TEXT,
        sector TEXT,
        geography TEXT,
        stage TEXT,

        revenue REAL,
        ebitda REAL,
        ebitda_margin REAL,
        growth REAL,

        enterprise_value REAL,
        entry_multiple REAL,
        exit_multiple REAL,
        leverage REAL,
        hold_period INTEGER,
        ownership REAL,

        investment_thesis TEXT,
        risks TEXT,

        score REAL,
        priority TEXT,

        owner TEXT,

        decision TEXT,
        decision_reason TEXT,
        decision_date TEXT
    )
    """)
    conn.commit()

init_db()

# =====================================================
# LOAD DATA (CRITICAL FIX)
# =====================================================
def load_data():
    conn2 = sqlite3.connect("deals.db", check_same_thread=False)
    df = pd.read_sql_query("SELECT * FROM deals ORDER BY id DESC", conn2)
    conn2.close()
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
st.sidebar.info(f"Role: {role}")

df = load_data()

# =====================================================
# DASHBOARD
# =====================================================
if page == "Dashboard":

    st.header("Dashboard")

    df = load_data()  # 🔥 CRITICAL FIX: refresh every time

    if df.empty:
        st.info("No deals yet.")
    else:
        for _, r in df.iterrows():

            col1, col2 = st.columns([5,1])

            with col1:
                st.write(f"**{r['company']}** | Score: {r['score']} | {r['stage']}")

            with col2:
                if st.button("Open", key=f"d_{r['id']}"):
                    open_deal(r["id"])

# =====================================================
# DEAL INTAKE (FULL INSTITUTIONAL)
# =====================================================
elif page == "Deal Intake":

    st.header("📥 Deal Intake (Institutional)")

    with st.form("deal_form"):

        col1, col2 = st.columns(2)

        with col1:
            company = st.text_input("Company Name")
            sector = st.selectbox("Sector", ["Tech","Healthcare","Industrials","Energy","Consumer","Financial Services"])
            geography = st.selectbox("Geography", ["USA","Europe","Asia","LATAM"])
            stage = st.selectbox("Stage", stages)

        with col2:
            revenue = st.number_input("Revenue ($M)", 1.0)
            ebitda = st.number_input("EBITDA ($M)", 1.0)
            ebitda_margin = st.number_input("EBITDA Margin (%)", 0.0, 100.0, 20.0)
            growth = st.slider("Growth (%)", -10.0, 100.0, 10.0)

        col3, col4 = st.columns(2)

        with col3:
            enterprise_value = st.number_input("Enterprise Value ($M)", 1.0)
            entry_multiple = st.slider("Entry Multiple", 1.0, 25.0, 8.0)
            exit_multiple = st.slider("Exit Multiple", 1.0, 25.0, 10.0)

        with col4:
            leverage = st.slider("Leverage (Debt/EBITDA)", 0.0, 10.0, 3.0)
            hold_period = st.slider("Hold Period (Years)", 1, 10, 5)
            ownership = st.slider("Ownership %", 10, 100, 100)

        investment_thesis = st.text_area("Investment Thesis")
        risks = st.text_area("Key Risks")
        owner = st.selectbox("Owner", ["Analyst","VP","Partner"])

        submitted = st.form_submit_button("Add Deal")

        if submitted:

            score = round((growth * 0.4) + (ebitda * 0.2), 2)

            c.execute("""
            INSERT INTO deals (
                date, company, sector, geography, stage,
                revenue, ebitda, ebitda_margin, growth,
                enterprise_value, entry_multiple, exit_multiple,
                leverage, hold_period, ownership,
                investment_thesis, risks,
                score, priority, owner,
                decision
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                str(datetime.date.today()),
                company, sector, geography, stage,
                revenue, ebitda, ebitda_margin, growth,
                enterprise_value, entry_multiple, exit_multiple,
                leverage, hold_period, ownership,
                investment_thesis, risks,
                score, priority(score), owner,
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
        col1, col2 = st.columns([5,1])

        with col1:
            st.write(f"**{r['company']}** | {r['score']} | {r['stage']}")

        with col2:
            if st.button("Open", key=f"p_{r['id']}"):
                open_deal(r["id"])

# =====================================================
# DEAL WORKSPACE
# =====================================================
elif page == "Deal Workspace":

    st.header("🧠 Deal Workspace")

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

    decision = st.selectbox("Decision", ["Pending","Approve","Reject","Hold"])
    reason = st.text_area("Rationale")

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
        st.rerun()

    st.divider()

    # =====================================================
    # DELETE (ROLE-BASED)
    # =====================================================
    st.subheader("🗑 Delete Deal")

    if role in ["VP","Partner","Executive"]:

        confirm = st.checkbox("Confirm deletion")

        if confirm and st.button("Delete Deal"):

            conn.execute("DELETE FROM deals WHERE id=?", (deal["id"],))
            conn.commit()

            st.session_state.deal_id = None
            st.session_state.page = "Pipeline"

            st.success("Deal deleted")
            st.rerun()

    else:
        st.info("No delete permissions")

# =====================================================
# DECISION CENTER
# =====================================================
elif page == "Decision Center":

    st.header("Decision Center")

    df_live = load_data()

    final = df_live[df_live["decision"].isin(["Approve","Reject","Hold"])]

    c1, c2, c3 = st.columns(3)
    c1.metric("Approved", len(df_live[df_live["decision"]=="Approve"]))
    c2.metric("Rejected", len(df_live[df_live["decision"]=="Reject"]))
    c3.metric("Hold", len(df_live[df_live["decision"]=="Hold"]))

    st.divider()

    if final.empty:
        st.info("No decisions yet")
    else:
        st.dataframe(final, use_container_width=True)
