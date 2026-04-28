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

st.title("🚀 DealFlow OS")
st.caption("VP-Level Investment Decision System (Final Build)")

# =====================================================
# UI POLISH (LIGHT)
# =====================================================
st.markdown("""
<style>
.block-container { padding-top: 2rem; }
h1, h2, h3 { font-weight: 600; }
</style>
""", unsafe_allow_html=True)

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

# =====================================================
# LOAD
# =====================================================
def load():
    return pd.read_sql_query("SELECT * FROM deals", conn)

df_raw = load()

# =====================================================
# ROLE SYSTEM
# =====================================================
role = st.sidebar.selectbox("Role", ["Analyst","VP","Partner","Executive"])
mode = st.sidebar.selectbox("Mode", ["Standard","Executive"])

permissions = {
    "Analyst": {
        "can_promote": False,
        "can_export": False,
        "views": ["Dashboard","Deal Intake","Pipeline","Deal Workspace"]
    },
    "VP": {
        "can_promote": True,
        "can_export": True,
        "views": ["Dashboard","Deal Intake","Pipeline","Deal Workspace","Decision Center"]
    },
    "Partner": {
        "can_promote": True,
        "can_export": True,
        "views": ["Dashboard","Pipeline","Deal Workspace","Decision Center"]
    },
    "Executive": {
        "can_promote": False,
        "can_export": True,
        "views": ["Dashboard","Pipeline","Decision Center"]
    }
}

st.sidebar.markdown("---")
st.sidebar.info(f"{role} | {mode}")

# =====================================================
# PRIORITY
# =====================================================
def priority(score):
    if score >= 10:
        return "🔥 Must Review"
    if score >= 7:
        return "🟡 High Priority"
    return "🔵 Watchlist"

# =====================================================
# LIFECYCLE
# =====================================================
stages = ["SOURCED", "SCREENED", "IC", "APPROVED", "CLOSED"]

def next_stage(current):
    if current not in stages:
        return "SOURCED"
    idx = stages.index(current)
    return stages[min(idx + 1, len(stages)-1)]

# =====================================================
# SCORE INSIGHT
# =====================================================
def explain_score(growth, ebitda, revenue=None, entry_multiple=None, sector=None):

    thesis = []

    # Growth narrative
    if growth > 25:
        thesis.append(
            f"The company exhibits strong top-line momentum with {growth:.1f}% growth, "
            "indicating scalable demand and potential market share expansion."
        )
    elif growth > 10:
        thesis.append(
            f"The business demonstrates moderate growth of {growth:.1f}%, "
            "suggesting a stable but not high-velocity expansion profile."
        )
    else:
        thesis.append(
            f"Growth is relatively subdued at {growth:.1f}%, "
            "which may indicate maturity or limited near-term upside."
        )

    # EBITDA quality
    if ebitda > 100:
        thesis.append(
            "EBITDA scale is strong, supporting the case for operational leverage "
            "and improved margin durability post-acquisition."
        )
    elif ebitda > 25:
        thesis.append(
            "EBITDA levels are mid-market, indicating a potentially stable cash flow base "
            "with room for efficiency improvements."
        )
    else:
        thesis.append(
            "EBITDA is relatively limited, suggesting either an early-stage business "
            "or one requiring operational improvement."
        )

    # Optional valuation lens
    if entry_multiple:
        if entry_multiple > 12:
            thesis.append(
                f"Entry multiple at {entry_multiple}x suggests elevated pricing, "
                "which may require strong execution to justify returns."
            )
        elif entry_multiple < 7:
            thesis.append(
                f"Entry multiple at {entry_multiple}x appears attractive relative to market norms, "
                "supporting a value-oriented investment thesis."
            )

    # Final synthesis (VP tone)
    conclusion = (
        "Overall, the investment presents a balanced profile of risk and opportunity. "
        "Further diligence should focus on revenue durability, margin expansion potential, "
        "and competitive positioning within the sector."
    )

    return " ".join(thesis + [conclusion])

# =====================================================
# NAVIGATION
# =====================================================
page = st.sidebar.radio(
    "Navigation",
    permissions[role]["views"]
)

# =====================================================
# FILTER
# =====================================================
def filter_role(df):

    if role == "Analyst":
        return df
    if role == "VP":
        return df[df["score"] >= 6]
    if role == "Partner":
        return df.sort_values("score", ascending=False).head(10)
    if role == "Executive":
        return df.sort_values("score", ascending=False).head(5)

    return df

df = filter_role(df_raw)

# =====================================================
# DASHBOARD
# =====================================================
if page == "Dashboard":

    st.header("Executive Overview")

    for _, r in df.iterrows():

        col1, col2 = st.columns([4, 1])

        with col1:
            st.write(f"**{r['company']}** | Score: {r['score']} | Stage: {r['stage']}")

        with col2:
            if st.button(f"Open", key=f"dash_{r['id']}"):
                st.session_state["deal_id"] = r["id"]
                st.rerun()

# =====================================================
# DEAL INTAKE
# =====================================================
elif page == "Deal Intake":

    st.header("📥 Deal Intake")

    with st.form("deal_form"):

        company = st.text_input("Company")

        sector = st.selectbox(
            "Sector",
            ["Technology","Healthcare","Business Services","Industrials","Consumer","Energy"]
        )

        ebitda = st.number_input("EBITDA ($M)", 0.0, 5000.0, 50.0)
        revenue = st.number_input("Revenue ($M)", 0.0, 20000.0, 100.0)

        growth = st.slider("Growth %", -20.0, 100.0, 10.0)

        size = st.number_input("EV ($M)", 0.0, 50000.0, 200.0)
        entry_multiple = st.slider("Entry Multiple", 1.0, 25.0, 8.0)

        ownership = st.slider("Ownership %", 0, 100, 100)

        owner = st.selectbox("Owner", ["Analyst","VP","Partner"])
        notes = st.text_area("Notes")

        submitted = st.form_submit_button("Add Deal")

        if submitted:

            # VALIDATION
            if not company:
                st.error("Company required")
                st.stop()

            if ebitda <= 0 or revenue <= 0:
                st.error("EBITDA and Revenue must be > 0")
                st.stop()

            # SCORING MODEL
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
            st.success("Deal successfully added")
            st.rerun()

# =====================================================
# PIPELINE
# =====================================================
elif page == "Pipeline":

    st.header("Pipeline")

    for _, r in df.iterrows():

        col1, col2 = st.columns([4,1])

        with col1:
            st.write(f"**{r['company']}** | Score: {r['score']} | Stage: {r['stage']}")

        with col2:
            if st.button("Open", key=r["id"]):
                st.session_state["deal_id"] = r["id"]
                st.session_state["page"] = "Deal Workspace"
                st.rerun()

# =====================================================
# 🚀 DEAL COCKPIT (FINAL UPGRADE)
# =====================================================
elif page == "Deal Workspace":

    st.header("🧠 Deal Cockpit")

    deal_id = st.session_state.get("deal_id")

    if not deal_id:
        st.warning("Select a deal from Pipeline or Dashboard")
        st.stop()

    deal = df_raw[df_raw["id"] == deal_id].iloc[0]

    # =================================================
    # HEADER STRIP
    # =================================================
    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Company", deal["company"])
    col2.metric("Score", deal["score"])
    col3.metric("Stage", deal["stage"])
    col4.metric("Priority", priority(deal["score"]))

    st.divider()

    # =================================================
    # FINANCIAL VIEW
    # =================================================
    st.subheader("📊 Financial Overview")

    st.write({
        "EBITDA": deal["ebitda"],
        "Revenue": deal["revenue"],
        "Growth": deal["growth"],
        "EV": deal["size"],
        "Entry Multiple": deal["entry_multiple"],
        "Ownership": deal["ownership"]
    })

    st.divider()

    # =================================================
    # LIFECYCLE CONTROL
    # =================================================
    st.subheader("🔄 Lifecycle Control")

    st.write("Current Stage:", deal["stage"])

    if permissions[role]["can_promote"]:

        if st.button("➡ Promote Stage"):

            new_stage = next_stage(deal["stage"])

            c.execute("""
            UPDATE deals
            SET stage=?
            WHERE id=?
            """, (new_stage, deal["id"]))

            conn.commit()
            st.success(f"Moved to {new_stage}")
            st.rerun()

    else:
        st.info("No promotion permission for this role")

    st.divider()

    # =================================================
    # DECISION PANEL
    # =================================================
    st.subheader("⚖️ Decision")

    decision = st.radio("Decision", ["Pending","Approve","Reject","Hold"])
    reason = st.text_area("Rationale")

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
        st.success("Saved")
        st.rerun()

    st.divider()

    # =================================================
    # INSIGHTS
    # =================================================
    st.subheader("🧠 Insight Layer")
    st.write(explain_score(
    deal["growth"],
    deal["ebitda"],
    deal.get("revenue"),
    deal.get("entry_multiple"),
    deal.get("sector")
))

    # =================================================
    # EXPORT
    # =================================================
    if permissions[role]["can_export"]:

        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)

        text = p.beginText(40, 750)
        text.textLine(f"IC MEMO - {deal['company']}")
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

# =====================================================
# DECISION CENTER
# =====================================================
elif page == "Decision Center":

    st.header("Decision Center")

    st.metric("Approved", len(df_raw[df_raw["decision"] == "Approve"]))
    st.metric("Rejected", len(df_raw[df_raw["decision"] == "Reject"]))
    st.metric("Hold", len(df_raw[df_raw["decision"] == "Hold"]))

    st.dataframe(df_raw)