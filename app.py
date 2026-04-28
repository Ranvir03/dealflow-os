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
# UI
# =====================================================
st.title("🚀 DealFlow OS")
st.caption("VP-Level Investment Decision System")

st.markdown("""
<style>
.block-container {padding-top: 1.5rem;}
h1,h2,h3 {font-weight: 700;}
div.stButton > button {border-radius: 8px;}
</style>
""", unsafe_allow_html=True)

# =====================================================
# SESSION STATE
# =====================================================
if "deal_id" not in st.session_state:
    st.session_state.deal_id = None

# =====================================================
# DATABASE
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
    idx = stages.index(current)
    return stages[min(idx + 1, len(stages)-1)]

def explain_score(growth, ebitda):
    notes = []

    if growth >= 20:
        notes.append("Strong growth profile.")
    elif growth <= 5:
        notes.append("Muted growth trajectory.")
    else:
        notes.append("Moderate growth profile.")

    if ebitda >= 100:
        notes.append("Strong EBITDA scale.")
    elif ebitda <= 20:
        notes.append("Smaller EBITDA base.")
    else:
        notes.append("Healthy mid-market EBITDA.")

    notes.append("Further diligence recommended.")
    return " ".join(notes)

def open_deal(deal_id):
    st.session_state.deal_id = int(deal_id)

# =====================================================
# ROLE SYSTEM
# =====================================================
role = st.sidebar.selectbox(
    "Role",
    ["Analyst", "VP", "Partner", "Executive"]
)

mode = st.sidebar.selectbox(
    "Mode",
    ["Standard", "Executive"]
)

permissions = {
    "Analyst": {
        "views": ["Dashboard", "Deal Intake", "Pipeline", "Deal Workspace"],
        "can_promote": False,
        "can_export": False,
        "can_delete": False
    },
    "VP": {
        "views": ["Dashboard", "Deal Intake", "Pipeline", "Deal Workspace", "Decision Center"],
        "can_promote": True,
        "can_export": True,
        "can_delete": True
    },
    "Partner": {
        "views": ["Dashboard", "Pipeline", "Deal Workspace", "Decision Center"],
        "can_promote": True,
        "can_export": True,
        "can_delete": True
    },
    "Executive": {
        "views": ["Dashboard", "Pipeline", "Decision Center"],
        "can_promote": False,
        "can_export": True,
        "can_delete": False
    }
}

page = st.sidebar.radio("Navigation", permissions[role]["views"])

st.sidebar.markdown("---")
st.sidebar.info(f"{role} | {mode}")

# =====================================================
# LOAD DATA
# =====================================================
df = load_data()

# =====================================================
# DASHBOARD
# =====================================================
if page == "Dashboard":

    st.header("Executive Overview")

    if df.empty:
        st.info("No deals available.")
    else:
        for _, r in df.iterrows():

            col1, col2 = st.columns([5,1])

            with col1:
                st.write(
                    f"**{r['company']}** | "
                    f"Score: {r['score']} | "
                    f"Stage: {r['stage']} | "
                    f"{r['priority']}"
                )

            with col2:
                if st.button("Open", key=f"dash_{r['id']}"):
                    open_deal(r["id"])
                    st.rerun()

# =====================================================
# DEAL INTAKE
# =====================================================
elif page == "Deal Intake":

    st.header("📥 Deal Intake")

    with st.form("deal_form", clear_on_submit=True):

        company = st.text_input("Company Name")

        sector = st.selectbox(
            "Sector",
            [
                "Technology",
                "Healthcare",
                "Business Services",
                "Industrials",
                "Consumer",
                "Energy",
                "Financial Services"
            ]
        )

        ebitda = st.number_input(
            "EBITDA ($M)",
            min_value=1.0,
            max_value=5000.0,
            value=25.0
        )

        revenue = st.number_input(
            "Revenue ($M)",
            min_value=1.0,
            max_value=50000.0,
            value=100.0
        )

        growth = st.slider(
            "Growth (%)",
            min_value=-10.0,
            max_value=100.0,
            value=12.0
        )

        size = st.number_input(
            "Enterprise Value ($M)",
            min_value=10.0,
            max_value=100000.0,
            value=250.0
        )

        entry_multiple = st.slider(
            "Entry Multiple (x)",
            min_value=1.0,
            max_value=25.0,
            value=8.0
        )

        ownership = st.slider(
            "Ownership (%)",
            min_value=10,
            max_value=100,
            value=100
        )

        owner = st.selectbox(
            "Deal Owner",
            ["Analyst", "VP", "Partner"]
        )

        notes = st.text_area("Investment Notes")

        submitted = st.form_submit_button("Add Deal")

        if submitted:

            if company.strip() == "":
                st.error("Company name required.")
                st.stop()

            score = round((growth * 0.35) + (ebitda * 0.25), 2)

            c.execute("""
            INSERT INTO deals (
                date, company, sector, ebitda, revenue, growth,
                size, entry_multiple, ownership, score,
                priority, stage, owner, notes,
                decision, decision_reason, decision_date
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                str(datetime.date.today()),
                company.strip(),
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
                "Pending",
                "",
                ""
            ))

            conn.commit()
            st.success("Deal added successfully.")
            st.rerun()

# =====================================================
# PIPELINE
# =====================================================
elif page == "Pipeline":

    st.header("Pipeline")

    if df.empty:
        st.info("No deals in pipeline.")
    else:
        for _, r in df.iterrows():

            col1, col2 = st.columns([5,1])

            with col1:
                st.write(
                    f"**{r['company']}** | "
                    f"Stage: {r['stage']} | "
                    f"Score: {r['score']}"
                )

            with col2:
                if st.button("Open", key=f"pipe_{r['id']}"):
                    open_deal(r["id"])
                    st.rerun()

# =====================================================
# DEAL WORKSPACE
# =====================================================
elif page == "Deal Workspace":

    st.header("🧠 Deal Cockpit")

    if not st.session_state.deal_id:
        st.warning("Select a deal from Dashboard or Pipeline.")
        st.stop()

    df_live = load_data()

    current = df_live[df_live["id"] == st.session_state.deal_id]

    if current.empty:
        st.warning("Deal not found.")
        st.session_state.deal_id = None
        st.stop()

    deal = current.iloc[0]

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Company", deal["company"])
    col2.metric("Score", deal["score"])
    col3.metric("Stage", deal["stage"])
    col4.metric("Priority", deal["priority"])

    st.divider()

    st.subheader("📊 Financial Overview")

    st.write({
        "Sector": deal["sector"],
        "EBITDA ($M)": deal["ebitda"],
        "Revenue ($M)": deal["revenue"],
        "Growth (%)": deal["growth"],
        "EV ($M)": deal["size"],
        "Entry Multiple": deal["entry_multiple"],
        "Ownership (%)": deal["ownership"]
    })

    st.divider()

    st.subheader("🔄 Lifecycle")

    st.info(f"Current Process Stage: {deal['stage']}")

    if permissions[role]["can_promote"]:
        if st.button("➡ Promote Stage"):

            new_stage = next_stage(deal["stage"])

            c.execute(
                "UPDATE deals SET stage=? WHERE id=?",
                (new_stage, deal["id"])
            )
            conn.commit()

            st.success(f"Moved to {new_stage}")
            st.rerun()

    st.divider()

    st.subheader("⚖️ Decision")

    current_decision = (
        deal["decision"]
        if pd.notna(deal["decision"]) and deal["decision"] != ""
        else "Pending"
    )

    options = ["Pending", "Approve", "Reject", "Hold"]

    decision = st.selectbox(
        "Decision",
        options,
        index=options.index(current_decision)
    )

    reason = st.text_area(
        "Rationale",
        value=deal["decision_reason"]
        if pd.notna(deal["decision_reason"])
        else ""
    )

    if st.button("Save Decision"):

        clean_decision = decision.strip().capitalize()

        c.execute("""
        UPDATE deals
        SET decision=?, decision_reason=?, decision_date=?
        WHERE id=?
        """, (
            clean_decision,
            reason,
            str(datetime.date.today()),
            deal["id"]
        ))

        conn.commit()

        st.success(f"Saved: {clean_decision}")
        st.rerun()

    st.divider()

    st.subheader("🧠 Insight Layer")
    st.write(explain_score(deal["growth"], deal["ebitda"]))

    st.divider()

    if permissions[role]["can_export"]:

        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)

        text = p.beginText(40, 750)
        text.textLine(f"IC Memo - {deal['company']}")
        text.textLine(f"Sector: {deal['sector']}")
        text.textLine(f"Score: {deal['score']}")
        text.textLine(f"Stage: {deal['stage']}")

        p.drawText(text)
        p.save()

        buffer.seek(0)

        st.download_button(
            "📄 Export IC Memo",
            data=buffer,
            file_name=f"{deal['company']}_IC.pdf",
            mime="application/pdf"
        )

    st.divider()

    if permissions[role]["can_delete"]:

        st.subheader("🗑 Danger Zone")

        confirm = st.checkbox("Confirm permanent deletion")

        if confirm:
            if st.button("Delete Deal"):

                c.execute(
                    "DELETE FROM deals WHERE id=?",
                    (deal["id"],)
                )
                conn.commit()

                st.session_state.deal_id = None

                st.success("Deal deleted.")
                st.rerun()

# =====================================================
# DECISION CENTER
# =====================================================
elif page == "Decision Center":

    st.header("Decision Center")

    df_live = load_data()

    df_live["decision"] = (
        df_live["decision"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.capitalize()
    )

    approved = df_live[df_live["decision"] == "Approve"]
    rejected = df_live[df_live["decision"] == "Reject"]
    hold = df_live[df_live["decision"] == "Hold"]

    c1, c2, c3 = st.columns(3)

    c1.metric("Approved", len(approved))
    c2.metric("Rejected", len(rejected))
    c3.metric("Hold", len(hold))

    st.divider()

    final_df = df_live[df_live["decision"].isin(["Approve","Reject","Hold"])]

    if final_df.empty:
        st.info("No finalized decisions yet.")
    else:
        st.dataframe(final_df, use_container_width=True)