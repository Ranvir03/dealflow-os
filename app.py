import streamlit as st
import pandas as pd
import sqlite3
import datetime

# =====================================================
# CONFIG
# =====================================================
st.set_page_config(page_title="DealFlow OS v3", layout="wide")

st.title("🚀 DealFlow OS v3")
st.caption("Clean Production Architecture (Fixed State + DB Sync)")

# =====================================================
# SESSION STATE
# =====================================================
if "deal_id" not in st.session_state:
    st.session_state.deal_id = None

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
        company TEXT UNIQUE,
        sector TEXT,
        stage TEXT,
        revenue REAL,
        ebitda REAL,
        growth REAL,
        score REAL,
        decision TEXT,
        decision_reason TEXT
    )
    """)
    conn.commit()

init_db()

# =====================================================
# ALWAYS FRESH DATA (CRITICAL FIX)
# =====================================================
def load_data():
    conn2 = sqlite3.connect("deals.db", check_same_thread=False)
    df = pd.read_sql_query("SELECT * FROM deals ORDER BY id DESC", conn2)
    conn2.close()
    return df

# =====================================================
# HELPERS
# =====================================================
stages = ["SOURCED", "SCREENED", "IC", "APPROVED", "CLOSED"]

def next_stage(stage):
    if stage not in stages:
        return "SOURCED"
    return stages[min(stages.index(stage) + 1, len(stages)-1)]

def score_calc(growth, ebitda):
    return round(growth * 0.4 + ebitda * 0.2, 2)

def open_deal(deal_id):
    st.session_state.deal_id = deal_id
    st.session_state.page = "Workspace"
    st.rerun()

# =====================================================
# NAVIGATION
# =====================================================
if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Deal Intake", "Decision Center", "Workspace"]
)

st.session_state.page = page

df = load_data()

# =====================================================
# DASHBOARD (LIVE SYNC FIX)
# =====================================================
if page == "Dashboard":

    st.header("Dashboard (Live)")

    df = load_data()  # 🔥 CRITICAL FIX

    if df.empty:
        st.info("No deals")
    else:
        for _, r in df.iterrows():

            col1, col2 = st.columns([5,1])

            with col1:
                st.write(f"**{r['company']}** | Score: {r['score']} | {r['stage']}")

            with col2:
                if st.button("Open", key=f"d_{r['id']}"):
                    open_deal(r["id"])

# =====================================================
# DEAL INTEL (NO DUPLICATES FIX)
# =====================================================
elif page == "Deal Intake":

    st.header("Deal Intake")

    with st.form("form"):

        company = st.text_input("Company")
        sector = st.selectbox("Sector", ["Tech","Healthcare","Energy","Industrials"])
        revenue = st.number_input("Revenue", 1.0)
        ebitda = st.number_input("EBITDA", 1.0)
        growth = st.slider("Growth", -10.0, 100.0, 10.0)

        submitted = st.form_submit_button("Add Deal")

        if submitted:

            if company.strip() == "":
                st.error("Company required")
                st.stop()

            # 🚨 DUPLICATE PROTECTION
            existing = c.execute(
                "SELECT * FROM deals WHERE company=?",
                (company,)
            ).fetchone()

            if existing:
                st.error("Deal already exists")
                st.stop()

            score = score_calc(growth, ebitda)

            c.execute("""
            INSERT INTO deals (
                date, company, sector, stage,
                revenue, ebitda, growth, score,
                decision
            )
            VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                str(datetime.date.today()),
                company,
                sector,
                "SOURCED",
                revenue,
                ebitda,
                growth,
                score,
                "Pending"
            ))

            conn.commit()
            st.success("Deal added")
            st.rerun()

# =====================================================
# DECISION CENTER (FIXED LIVE UPDATE)
# =====================================================
elif page == "Decision Center":

    st.header("Decision Center (Live)")

    df = load_data()

    approved = df[df["decision"] == "Approve"]
    rejected = df[df["decision"] == "Reject"]
    hold = df[df["decision"] == "Hold"]

    col1, col2, col3 = st.columns(3)
    col1.metric("Approved", len(approved))
    col2.metric("Rejected", len(rejected))
    col3.metric("Hold", len(hold))

    st.divider()

    st.dataframe(df[df["decision"] != "Pending"], use_container_width=True)

# =====================================================
# WORKSPACE (STATE FIXED + DELETE FIX)
# =====================================================
elif page == "Workspace":

    st.header("Deal Workspace")

    deal_id = st.session_state.get("deal_id")

    if not deal_id:
        st.warning("Select a deal")
        st.stop()

    df = load_data()
    deal_row = df[df["id"] == deal_id]

    if deal_row.empty:
        st.warning("Deal not found")
        st.stop()

    deal = deal_row.iloc[0]

    st.subheader(deal["company"])

    st.progress(
        stages.index(deal["stage"]) / (len(stages)-1)
    )

    st.write(f"Stage: {deal['stage']}")

    # =====================
    # DECISION
    # =====================
    decision = st.selectbox(
        "Decision",
        ["Pending","Approve","Reject","Hold"]
    )

    reason = st.text_area("Reason")

    if st.button("Save Decision"):

        c.execute("""
        UPDATE deals
        SET decision=?, decision_reason=?
        WHERE id=?
        """, (
            decision,
            reason,
            deal["id"]
        ))

        conn.commit()
        st.success("Saved")
        st.rerun()

    st.divider()

    # =====================
    # DELETE FIX (GLOBAL SYNC)
    # =====================
    st.subheader("Danger Zone")

    confirm = st.checkbox("Confirm delete")

    if confirm and st.button("Delete Deal"):

        c.execute("DELETE FROM deals WHERE id=?", (deal["id"],))
        conn.commit()

        st.session_state.deal_id = None
        st.session_state.page = "Dashboard"

        st.success("Deleted")
        st.rerun()