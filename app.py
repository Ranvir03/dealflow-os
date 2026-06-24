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
# =====================================================
# SCORING ENGINE
# =====================================================
# Each deal is scored on four dimensions, normalized to 0-100, then
# combined into a weighted composite (0-100). Weights reflect a standard
# PE/buyout screen: valuation discipline carries the most weight because
# overpaying at entry is the surest way to impair returns.
SCORE_WEIGHTS = {
    "Valuation discipline": 0.30,
    "Growth": 0.25,
    "Profitability": 0.25,
    "Scale": 0.20,
}

def _normalize(value, low, high):
    """Linear-scale a raw metric onto 0-100, clamped at both ends."""
    if high == low:
        return 0.0
    pct = (value - low) / (high - low)
    return round(max(0.0, min(1.0, pct)) * 100, 1)

def score_components(growth, ebitda, revenue, entry_multiple):
    """Return the 0-100 sub-score for each scoring dimension."""
    margin = (ebitda / revenue * 100) if revenue else 0.0
    return {
        # Entry multiple, lower = cheaper: 5x -> 100, 15x -> 0
        "Valuation discipline": _normalize(15 - entry_multiple, 0, 10),
        # Revenue growth: 0% -> 0, 30%+ -> 100
        "Growth": _normalize(growth, 0, 30),
        # EBITDA margin: 5% -> 0, 35%+ -> 100
        "Profitability": _normalize(margin, 5, 35),
        # EBITDA scale ($M): 5 -> 0, 150+ -> 100
        "Scale": _normalize(ebitda, 5, 150),
    }

def score_deal(growth, ebitda, revenue, entry_multiple):
    """Composite 0-100 score from the weighted dimension sub-scores."""
    comps = score_components(growth, ebitda, revenue, entry_multiple)
    composite = sum(comps[k] * SCORE_WEIGHTS[k] for k in SCORE_WEIGHTS)
    return round(composite, 1)

def score_table(growth, ebitda, revenue, entry_multiple):
    """Build a per-dimension breakdown table for the UI."""
    comps = score_components(growth, ebitda, revenue, entry_multiple)
    rows = [
        {
            "Dimension": dim,
            "Sub-score (0–100)": comps[dim],
            "Weight": f"{int(SCORE_WEIGHTS[dim] * 100)}%",
            "Contribution": round(comps[dim] * SCORE_WEIGHTS[dim], 1),
        }
        for dim in SCORE_WEIGHTS
    ]
    return pd.DataFrame(rows)

def priority(score):
    if score >= 70:
        return "🔥 Must Review"
    elif score >= 50:
        return "🟡 High Priority"
    return "🔵 Watchlist"

stages = ["SOURCED", "SCREENED", "IC", "APPROVED", "CLOSED"]

def next_stage(current):
    if current not in stages:
        return "SOURCED"
    idx = stages.index(current)
    return stages[min(idx + 1, len(stages)-1)]

def explain_score(growth, ebitda, revenue, entry_multiple):
    comps = score_components(growth, ebitda, revenue, entry_multiple)
    best = max(comps, key=comps.get)
    worst = min(comps, key=comps.get)
    return (
        f"Strongest dimension: **{best}** ({comps[best]:.0f}/100). "
        f"Weakest dimension: **{worst}** ({comps[worst]:.0f}/100). "
        f"Composite reflects a valuation-disciplined buyout screen; "
        f"further diligence recommended."
    )

def open_deal(deal_id):
    st.session_state.deal_id = int(deal_id)
    # Request a jump to the workspace; honored before the nav radio is drawn.
    st.session_state._nav_to = "Deal Workspace"

# =====================================================
# RETURNS MODEL (first-pass LBO screen)
# =====================================================
# Simple sponsor-returns screen: buy at entry_multiple x EBITDA, grow EBITDA
# at the deal's growth rate over the hold, exit at exit_multiple. Debt is held
# flat (no amortization) to keep the mechanics transparent. A single entry /
# single exit cash flow gives MOIC and IRR.
def returns_model(ebitda0, growth_pct, entry_multiple, exit_multiple,
                  hold_years, leverage_pct, ownership_pct):
    g = growth_pct / 100.0
    own = ownership_pct / 100.0
    lev = leverage_pct / 100.0

    entry_ev = entry_multiple * ebitda0
    debt = lev * entry_ev
    entry_equity = entry_ev - debt

    exit_ebitda = ebitda0 * ((1 + g) ** hold_years)
    exit_ev = exit_multiple * exit_ebitda
    exit_equity = exit_ev - debt

    invested = own * entry_equity
    proceeds = own * exit_equity

    if entry_equity > 0:
        moic = exit_equity / entry_equity
    else:
        moic = float("nan")

    if moic == moic and moic > 0 and hold_years > 0:  # moic==moic filters NaN
        irr = moic ** (1.0 / hold_years) - 1.0
    else:
        irr = float("nan")

    return {
        "entry_ev": entry_ev,
        "exit_ebitda": exit_ebitda,
        "exit_ev": exit_ev,
        "invested_equity": invested,
        "exit_proceeds": proceeds,
        "moic": moic,
        "irr": irr,
    }

def irr_sensitivity(ebitda0, growth_pct, entry_multiple, exit_multiple,
                    hold_years, leverage_pct, ownership_pct):
    """IRR grid across a range of exit multiples (cols) x hold periods (rows)."""
    exit_mults = [max(1.0, exit_multiple + d) for d in (-2, -1, 0, 1, 2)]
    holds = [3, 4, 5, 6, 7]
    data = {}
    for em in exit_mults:
        col = {}
        for h in holds:
            r = returns_model(ebitda0, growth_pct, entry_multiple, em,
                              h, leverage_pct, ownership_pct)
            col[f"{h}y"] = (round(r["irr"] * 100, 1)
                            if r["irr"] == r["irr"] else None)
        data[f"{em:.1f}x"] = col
    return pd.DataFrame(data)

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

# Honor a pending navigation request (e.g. from an "Open" button) before the
# radio is instantiated, so clicking Open actually lands on the workspace.
if st.session_state.get("_nav_to"):
    target = st.session_state.pop("_nav_to")
    if target in permissions[role]["views"]:
        st.session_state.nav = target

page = st.sidebar.radio("Navigation", permissions[role]["views"], key="nav")

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

    st.caption("Fields update individually — the deal is only saved when you click **Add Deal**.")

    # Standalone widgets (not wrapped in st.form) so pressing Enter in a field
    # just commits that field instead of submitting the entire deal.
    company = st.text_input("Company Name", key="di_company")

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
        ],
        key="di_sector"
    )

    ebitda = st.number_input(
        "EBITDA ($M)",
        min_value=1.0,
        max_value=5000.0,
        value=25.0,
        key="di_ebitda"
    )

    revenue = st.number_input(
        "Revenue ($M)",
        min_value=1.0,
        max_value=50000.0,
        value=100.0,
        key="di_revenue"
    )

    growth = st.slider(
        "Growth (%)",
        min_value=-10.0,
        max_value=100.0,
        value=12.0,
        key="di_growth"
    )

    size = st.number_input(
        "Enterprise Value ($M)",
        min_value=10.0,
        max_value=100000.0,
        value=250.0,
        key="di_size"
    )

    entry_multiple = st.slider(
        "Entry Multiple (x)",
        min_value=1.0,
        max_value=25.0,
        value=8.0,
        key="di_entry"
    )

    ownership = st.slider(
        "Ownership (%)",
        min_value=10,
        max_value=100,
        value=100,
        key="di_ownership"
    )

    owner = st.selectbox(
        "Deal Owner",
        ["Analyst", "VP", "Partner"],
        key="di_owner"
    )

    notes = st.text_area("Investment Notes", key="di_notes")

    # Live preview so the user sees the score before committing.
    preview = score_deal(growth, ebitda, revenue, entry_multiple)
    st.info(f"Projected score: **{preview}/100** — {priority(preview)}")

    if st.button("Add Deal", type="primary"):

        if company.strip() == "":
            st.error("Company name required.")
            st.stop()

        score = score_deal(growth, ebitda, revenue, entry_multiple)

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

        # Clear the inputs by dropping their widget state, then rerun.
        for k in [
            "di_company", "di_sector", "di_ebitda", "di_revenue",
            "di_growth", "di_size", "di_entry", "di_ownership",
            "di_owner", "di_notes"
        ]:
            st.session_state.pop(k, None)

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

    st.subheader("💰 Returns Analysis (MOIC / IRR)")
    st.caption(
        "First-pass sponsor returns. Adjust the exit assumptions below; debt is "
        "held flat (no amortization) to keep the mechanics transparent."
    )

    ra1, ra2, ra3 = st.columns(3)
    hold_years = ra1.slider("Hold period (yrs)", 1, 10, 5, key="ra_hold")
    exit_multiple = ra2.slider(
        "Exit multiple (x)", 1.0, 25.0,
        float(deal["entry_multiple"]), step=0.5, key="ra_exit"
    )
    leverage_pct = ra3.slider(
        "Leverage (debt % of EV)", 0, 80, 50, key="ra_lev"
    )

    r = returns_model(
        deal["ebitda"], deal["growth"], deal["entry_multiple"],
        exit_multiple, hold_years, leverage_pct, deal["ownership"]
    )

    def _fmt(v, suffix="", nd=2):
        return f"{v:.{nd}f}{suffix}" if v == v else "n/m"  # v==v filters NaN

    m1, m2, m3 = st.columns(3)
    m1.metric("MOIC", _fmt(r["moic"], "x"))
    m2.metric("IRR", _fmt(r["irr"] * 100 if r["irr"] == r["irr"] else r["irr"], "%", 1))
    m3.metric("Exit EBITDA ($M)", _fmt(r["exit_ebitda"], "", 1))

    m4, m5, m6 = st.columns(3)
    m4.metric("Entry EV ($M)", _fmt(r["entry_ev"], "", 0))
    m5.metric("Exit EV ($M)", _fmt(r["exit_ev"], "", 0))
    m6.metric(
        "Equity in → out ($M)",
        f"{r['invested_equity']:.0f} → {r['exit_proceeds']:.0f}"
    )

    with st.expander("📊 IRR sensitivity — exit multiple × hold period"):
        st.caption("IRR (%) by exit multiple (columns) and hold period (rows).")
        st.dataframe(
            irr_sensitivity(
                deal["ebitda"], deal["growth"], deal["entry_multiple"],
                exit_multiple, hold_years, leverage_pct, deal["ownership"]
            ),
            use_container_width=True,
        )

    st.divider()

    st.subheader("🔄 Lifecycle")

    st.info(f"Current Process Stage: {deal['stage']}")

    if permissions[role]["can_promote"]:
        if st.button("➡ Promote Stage"):

            new_stage = next_stage(deal["stage"])

            c.execute(
                "UPDATE deals SET stage=? WHERE id=?",
                (new_stage, int(deal["id"]))
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
            int(deal["id"])
        ))

        conn.commit()

        st.success(f"Saved: {clean_decision}")
        st.rerun()

    st.divider()

    st.subheader("🧠 Insight Layer")
    st.write(explain_score(
        deal["growth"], deal["ebitda"], deal["revenue"], deal["entry_multiple"]
    ))

    with st.expander("📐 Score methodology & breakdown", expanded=True):
        margin = (deal["ebitda"] / deal["revenue"] * 100) if deal["revenue"] else 0.0
        st.caption(
            f"Composite score {deal['score']}/100 — weighted across four "
            f"dimensions. EBITDA margin: {margin:.1f}%."
        )
        st.dataframe(
            score_table(
                deal["growth"], deal["ebitda"],
                deal["revenue"], deal["entry_multiple"]
            ),
            use_container_width=True,
            hide_index=True,
        )

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
                    (int(deal["id"]),)
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