import streamlit as st
import pandas as pd
import sqlite3
import datetime

# =====================================================
# CONFIG
# =====================================================
st.set_page_config(page_title="DealFlow OS", layout="wide")

# =====================================================
# STATE
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
        company TEXT,
        sector TEXT,
        revenue REAL,
        ebitda REAL,
        growth REAL,
        score REAL,
        stage TEXT,
        decision TEXT,
        decision_reason TEXT
    )
    """)
    conn.commit()

init_db()

# =====================================================
# ALWAYS FRESH DATA
# =====================================================
def load_data():
    conn2 = sqlite3.connect("deals.db", check_same_thread=False)
    df = pd.read_sql_query("SELECT * FROM deals ORDER BY id DESC", conn2)
    conn2.close()
    return df

# =====================================================
# ROLE SYSTEM (RESTORED)
# =====================================================
role = st.sidebar.selectbox("Role", ["Analyst","VP","Partner","Executive"])

permissions = {
    "Analyst": ["Dashboard","Intake","Pipeline","Workspace"],
    "VP": ["Dashboard","Intake","Pipeline","Workspace","Decision Center"],
    "Partner": ["Dashboard","Pipeline","Workspace","Decision Center"],
    "Executive": ["Dashboard","Pipeline","Decision Center"]
}

pages = permissions[role]
page = st.sidebar.radio("Navigation", pages)

# =====================================================
# HELPERS
# =====================================================
def score_calc(growth, ebitda):
    return round(growth * 0.4 + ebitda * 0.2, 2)

# =====================================================
# DASHBOARD (FIXED LIVE STATE)
# =====================================================
if page == "Dashboard":

    st.header("Dashboard")

    df = load_data()

    for _, r in df.iterrows():

        col1, col2 = st.columns([5,1])

        with col1:
            st.write(f"**{r['company']}** | Score: {r['score']} | {r['stage']}")

        with col2:
            if st.button("Open", key=f"d_{r['id']}"):
                st.session_state.deal_id = r["id"]
                st.session_state.page = "Workspace"
                st.rerun()

# =====================================================
# DEAL INTAKE (NO DUPLICATES + CLEAN)
# =====================================================
elif page == "Intake":

    st.header("Deal Intake")

    with st.form("form"):

        company = st.text_input("Company")
        sector = st.selectbox("Sector", ["Tech","Healthcare","Energy"])
        revenue = st.number_input("Revenue", 1.0)
        ebitda = st.number_input("EBITDA", 1.0)
        growth = st.slider("Growth", -10.0, 100.0, 10.0)

        submitted = st.form_submit_button("Add Deal")

        if submitted:

            if company.strip() == "":
                st.error("Company required")
                st.stop()

            # prevent duplicates
            exists = c.execute(
                "SELECT id FROM deals WHERE company=?",
                (company,)
            ).fetchone()

            if exists:
                st.error("Deal already exists")
                st.stop()

            score = score_calc(growth, ebitda)

            c.execute("""
            INSERT INTO deals (
                date, company, sector, revenue,
                ebitda, growth, score, stage, decision
            )
            VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                str(datetime.date.today()),
                company, sector, revenue,
                ebitda, growth, score,
                "SOURCED",
                "Pending"
            ))

            conn.commit()
            st.success("Added")
            st.rerun()

# =====================================================
# PIPELINE
# =====================================================
elif page == "Pipeline":

    st.header("Pipeline")

    df = load_data()

    for _, r in df.iterrows():

        col1, col2 = st.columns([5,1])

        with col1:
            st.write(f"{r['company']} | {r['score']}")

        with col2:
            if st.button("Open", key=f"p_{r['id']}"):
                st.session_state.deal_id = r["id"]
                st.rerun()

# =====================================================
# WORKSPACE (FIXED STATE + DELETE + DECISION)
# =====================================================
elif page == "Workspace":

    st.header("Workspace")

    deal_id = st.session_state.get("deal_id")

    if not deal_id:
        st.warning("Select deal")
        st.stop()

    df = load_data()
    deal_df = df[df["id"] == deal_id]

    if deal_df.empty:
        st.warning("Deal not found")
        st.stop()

    deal = deal_df.iloc[0]

    st.write(f"Company: {deal['company']}")
    st.write(f"Stage: {deal['stage']}")

    # =====================
    # DECISION FIXED
    # =====================
    decision = st.selectbox("Decision", ["Pending","Approve","Reject","Hold"])
    reason = st.text_area("Reason")

    if st.button("Save Decision"):

        c.execute("""
        UPDATE deals
        SET decision=?, decision_reason=?
        WHERE id=?
        """, (decision, reason, deal["id"]))

        conn.commit()
        st.success("Saved")
        st.rerun()

    st.divider()

    # =====================
    # DELETE FIXED (GLOBAL SYNC)
    # =====================
    if role in ["VP","Partner","Executive"]:

        confirm = st.checkbox("Confirm delete")

        if confirm and st.button("Delete Deal"):

            c.execute("DELETE FROM deals WHERE id=?", (deal["id"],))
            conn.commit()

            st.session_state.deal_id = None
            st.rerun()

    else:
        st.info("No delete permission")

# =====================================================
# DECISION CENTER (FIXED LIVE)
# =====================================================
elif page == "Decision Center":

    st.header("Decision Center")

    df = load_data()

    final = df[df["decision"].isin(["Approve","Reject","Hold"])]

    st.metric("Approved", len(df[df["decision"]=="Approve"]))
    st.metric("Rejected", len(df[df["decision"]=="Reject"]))
    st.metric("Hold", len(df[df["decision"]=="Hold"]))

    st.divider()

    st.dataframe(final)