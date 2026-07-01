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
st.caption("M&A & Capital Advisory — Deal Execution & Engagement Management")

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

    # Engagement / fee columns added post-hoc so existing databases migrate
    # cleanly instead of erroring on a schema mismatch.
    existing = [row[1] for row in c.execute("PRAGMA table_info(deals)").fetchall()]
    for col, coltype in [
        ("deal_type", "TEXT"),
        ("retainer", "REAL"),
        ("success_fee_pct", "REAL"),
        ("geography", "TEXT"),
        ("origination", "TEXT"),
        ("target_close", "TEXT"),
        ("raise_round", "TEXT"),
        ("scope", "TEXT"),
    ]:
        if col not in existing:
            c.execute(f"ALTER TABLE deals ADD COLUMN {col} {coltype}")

    # Counterparty CRM: buyers / investors tracked against each engagement.
    c.execute("""
    CREATE TABLE IF NOT EXISTS counterparties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        deal_id INTEGER,
        name TEXT,
        cp_type TEXT,
        status TEXT,
        indicative_value REAL,
        notes TEXT,
        updated TEXT
    )
    """)
    conn.commit()

init_db()

def load_data():
    return pd.read_sql_query("SELECT * FROM deals ORDER BY id DESC", conn)

def load_counterparties(deal_id):
    return pd.read_sql_query(
        "SELECT * FROM counterparties WHERE deal_id=? ORDER BY id DESC",
        conn, params=(int(deal_id),)
    )

# =====================================================
# ENGAGEMENT MODEL
# =====================================================
# Engagement types cover the core advisory mandates a boutique / mid-market
# bank runs. Kept generic so the tool fits any firm, not one in particular.
DEAL_TYPES = [
    "Sell-side M&A",
    "Buy-side M&A",
    "Capital Raise — Equity",
    "Capital Raise — Debt",
    "Restructuring",
    "Strategic Advisory",
]

SECTORS = [
    "Technology / Software",
    "Healthcare",
    "Financial Services",
    "Industrials",
    "Consumer & Retail",
    "Business Services",
    "Energy & Utilities",
    "Media & Telecom",
    "Real Estate",
    "Other",
]

ORIGINATION = ["Proprietary", "Referral", "Inbound", "Repeat Client"]

RAISE_ROUNDS = ["Seed", "Series A", "Series B", "Series C",
                "Growth / Late Stage", "Debt", "Other"]

# Currency unit -> factor that converts a typed amount into $M (canonical).
# Lets the user type figures in whatever unit they like instead of being
# forced to pre-divide everything into millions.
UNIT_FACTORS = {
    "Dollars": 1e-6,
    "Thousands ($K)": 1e-3,
    "Millions ($M)": 1.0,
    "Billions ($B)": 1000.0,
}

# Outreach funnel a live M&A process runs each buyer/investor through.
CP_STAGES = ["Identified", "Contacted", "NDA Signed",
             "IOI Received", "LOI Received", "Passed"]

CP_TYPES = ["Strategic", "Financial (PE)", "Family Office", "Other"]

def _num(v):
    """Coerce None / NaN / bad values to 0.0 for fee math."""
    try:
        v = float(v)
        return 0.0 if v != v else v  # v != v is True only for NaN
    except (TypeError, ValueError):
        return 0.0

def estimated_fees(retainer_k, success_fee_pct, transaction_value_m):
    """Return (retainer $M, success fee $M, total $M).

    Retainer is entered in $K; success fee is a % of the transaction value
    (EV, in $M). This is the standard boutique structure: a fixed retainer
    plus a success fee earned on close.
    """
    retainer_m = _num(retainer_k) / 1000.0
    success_m = _num(success_fee_pct) / 100.0 * _num(transaction_value_m)
    return retainer_m, success_m, retainer_m + success_m

def fmt_money_m(m):
    """Format a $M value into a readable $K / $M / $B string."""
    m = _num(m)
    if m == 0:
        return "$0"
    if abs(m) >= 1000:
        return f"${m / 1000:.2f}B"
    if abs(m) >= 1:
        return f"${m:.1f}M"
    return f"${m * 1000:.0f}K"

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

# Sell-side M&A engagement lifecycle (pitch through close).
stages = ["PITCH", "MANDATED", "PREPARATION", "MARKETING",
          "DILIGENCE", "CLOSING", "CLOSED"]

def next_stage(current):
    if current not in stages:
        return "PITCH"
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
        st.info("No engagements available.")
    else:
        # Fee-pipeline backlog: sum of estimated total fees across engagements.
        total_fee = sum(
            estimated_fees(r.get("retainer"), r.get("success_fee_pct"), r.get("size"))[2]
            for _, r in df.iterrows()
        )
        live = df[df["stage"] != "CLOSED"] if "stage" in df else df

        k1, k2, k3 = st.columns(3)
        k1.metric("Active Engagements", len(live))
        k2.metric("Total Engagements", len(df))
        k3.metric("Est. Fee Pipeline", f"${total_fee:.1f}M")

        st.divider()

        for _, r in df.iterrows():

            col1, col2 = st.columns([5,1])

            etype = r["deal_type"] if pd.notna(r.get("deal_type")) else "—"
            _, _, tot = estimated_fees(
                r.get("retainer"), r.get("success_fee_pct"), r.get("size")
            )

            with col1:
                st.write(
                    f"**{r['company']}** | "
                    f"{etype} | "
                    f"Stage: {r['stage']} | "
                    f"Fee: ${tot:.1f}M | "
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

    st.header("📥 New Engagement")

    st.caption("Fields update individually — the engagement is only saved when you click **Add Engagement**. "
               "Fields adapt to the engagement type you pick.")

    # ---- Core engagement details (all types) ----
    company = st.text_input("Client / Company", key="di_company")

    t1, t2 = st.columns(2)
    deal_type = t1.selectbox("Engagement Type", DEAL_TYPES, key="di_type")
    sector = t2.selectbox("Sector", SECTORS, key="di_sector")

    o1, o2, o3 = st.columns(3)
    geography = o1.text_input("Geography", placeholder="e.g. US, India, Cross-border", key="di_geo")
    origination = o2.selectbox("Origination", ORIGINATION, key="di_orig")
    owner = o3.selectbox("Deal Lead", ["Analyst", "VP", "Partner", "MD"], key="di_owner")

    target_close = st.date_input("Target Close (optional)", value=None, key="di_close")

    st.divider()

    # ---- Amount unit selector (no field is silently assumed to be $M) ----
    st.markdown("**Amounts** — choose the unit you want to type in.")
    unit = st.selectbox("Amounts entered in", list(UNIT_FACTORS.keys()),
                        index=2, key="di_unit")
    factor = UNIT_FACTORS[unit]  # multiply a typed amount to get $M

    # ---- Financial snapshot (all types) ----
    f1, f2, f3 = st.columns(3)
    revenue_raw = f1.number_input(f"Revenue ({unit})", min_value=0.0, value=0.0, key="di_revenue")
    ebitda_raw = f2.number_input(f"EBITDA ({unit})", min_value=0.0, value=0.0, key="di_ebitda")
    growth = f3.number_input("Revenue Growth (%)", min_value=-50.0, max_value=300.0,
                             value=0.0, step=1.0, key="di_growth")

    revenue = revenue_raw * factor  # canonical $M
    ebitda = ebitda_raw * factor    # canonical $M
    margin = (ebitda / revenue * 100) if revenue else 0.0
    if revenue:
        st.caption(f"Revenue {fmt_money_m(revenue)} · EBITDA {fmt_money_m(ebitda)} · "
                   f"Margin {margin:.1f}%")

    # ---- Conditional fields by engagement type ----
    size = 0.0            # transaction value ($M) — drives the success fee
    entry_multiple = 0.0  # expected EV/EBITDA (advisory estimate)
    raise_round = ""
    scope = ""

    if deal_type in ("Sell-side M&A", "Buy-side M&A", "Restructuring"):
        m1, m2 = st.columns(2)
        tv_raw = m1.number_input(f"Expected Transaction Value ({unit})",
                                 min_value=0.0, value=0.0, key="di_tv")
        size = tv_raw * factor
        entry_multiple = m2.number_input("Expected EV / EBITDA (x)", min_value=0.0,
                                         max_value=50.0, value=8.0, step=0.5, key="di_mult")
        if size:
            st.caption(f"Transaction value: {fmt_money_m(size)}")

    elif deal_type in ("Capital Raise — Equity", "Capital Raise — Debt"):
        r1, r2 = st.columns(2)
        raise_round = r1.selectbox("Round", RAISE_ROUNDS, key="di_round")
        amt_raw = r2.number_input(f"Amount Sought ({unit})", min_value=0.0,
                                  value=0.0, key="di_amt")
        size = amt_raw * factor
        if deal_type == "Capital Raise — Equity":
            pm_raw = st.number_input(f"Pre-money Valuation ({unit}, optional)",
                                     min_value=0.0, value=0.0, key="di_premoney")
            premoney = pm_raw * factor
            entry_multiple = (premoney / ebitda) if ebitda else 0.0
        if size:
            st.caption(f"Amount sought: {fmt_money_m(size)}")

    else:  # Strategic Advisory
        scope = st.text_area("Scope / Objective", key="di_scope",
                             placeholder="What is the mandate? (no transaction value)")

    st.divider()

    # ---- Fee economics (all types) ----
    st.markdown("**Fee Economics**")
    fee1, fee2 = st.columns(2)
    retainer = fee1.number_input("Retainer ($K)", min_value=0.0, max_value=100000.0,
                                 value=50.0, step=5.0, key="di_retainer")
    success_fee_pct = fee2.number_input("Success Fee (% of transaction value)",
                                        min_value=0.0, max_value=15.0, value=2.0,
                                        step=0.25, key="di_successfee")

    notes = st.text_area("Deal Notes", key="di_notes")

    # ---- Live preview ----
    _, _, tot_fee = estimated_fees(retainer, success_fee_pct, size)
    score = score_deal(growth, ebitda, revenue, entry_multiple) if (ebitda and revenue) else 0.0
    preview = (
        f"Transaction value: **{fmt_money_m(size)}**  |  "
        f"Est. total fee: **{fmt_money_m(tot_fee)}**"
    )
    if score:
        preview += f"  |  Screen score: **{score:.0f}/100** ({priority(score)})"
    st.info(preview)

    if st.button("Add Engagement", type="primary"):

        if company.strip() == "":
            st.error("Client / company name required.")
            st.stop()

        score = score_deal(growth, ebitda, revenue, entry_multiple)
        close_str = str(target_close) if target_close else ""

        c.execute("""
        INSERT INTO deals (
            date, company, sector, ebitda, revenue, growth,
            size, entry_multiple, ownership, score,
            priority, stage, owner, notes,
            decision, decision_reason, decision_date,
            deal_type, retainer, success_fee_pct,
            geography, origination, target_close, raise_round, scope
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            str(datetime.date.today()),
            company.strip(),
            sector,
            ebitda,
            revenue,
            growth,
            size,
            entry_multiple,
            100,  # ownership retained for the returns model; not an intake field
            score,
            priority(score),
            "PITCH",
            owner,
            notes,
            "Pending",
            "",
            "",
            deal_type,
            retainer,
            success_fee_pct,
            geography,
            origination,
            close_str,
            raise_round,
            scope
        ))

        conn.commit()

        # Clear the inputs by dropping their widget state, then rerun.
        for k in [
            "di_company", "di_type", "di_sector", "di_geo", "di_orig", "di_owner",
            "di_close", "di_unit", "di_revenue", "di_ebitda", "di_growth",
            "di_tv", "di_mult", "di_round", "di_amt", "di_premoney", "di_scope",
            "di_retainer", "di_successfee", "di_notes"
        ]:
            st.session_state.pop(k, None)

        st.success("Engagement added successfully.")
        st.rerun()

# =====================================================
# PIPELINE
# =====================================================
elif page == "Pipeline":

    st.header("Pipeline")

    if df.empty:
        st.info("No engagements in pipeline.")
    else:
        for _, r in df.iterrows():

            col1, col2 = st.columns([5,1])

            etype = r["deal_type"] if pd.notna(r.get("deal_type")) else "—"

            with col1:
                st.write(
                    f"**{r['company']}** | "
                    f"{etype} | "
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

    margin = (_num(deal["ebitda"]) / _num(deal["revenue"]) * 100) if _num(deal["revenue"]) else 0.0
    mult = _num(deal["entry_multiple"])
    st.write({
        "Sector": deal["sector"],
        "Revenue": fmt_money_m(deal["revenue"]),
        "EBITDA": fmt_money_m(deal["ebitda"]),
        "EBITDA margin": f"{margin:.1f}%",
        "Revenue growth": f"{_num(deal['growth']):.1f}%",
        "Transaction value": fmt_money_m(deal["size"]),
        "Expected EV/EBITDA": f"{mult:.1f}x" if mult else "—",
    })

    st.divider()

    # -------------------------------------------------
    # ENGAGEMENT & FEE ECONOMICS
    # -------------------------------------------------
    st.subheader("🏦 Engagement & Fee Economics")

    def _field(v):
        return v if (pd.notna(v) and str(v).strip()) else "—"

    etype = _field(deal["deal_type"])
    ret_k = _num(deal["retainer"])
    sf_pct = _num(deal["success_fee_pct"])
    ret_m, succ_m, tot_m = estimated_fees(ret_k, sf_pct, deal["size"])

    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Engagement", etype)
    e2.metric("Transaction Value", fmt_money_m(deal["size"]))
    e3.metric("Success Fee", f"{sf_pct:.2f}%")
    e4.metric("Est. Total Fee", fmt_money_m(tot_m))

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Geography", _field(deal["geography"]))
    d2.metric("Origination", _field(deal["origination"]))
    d3.metric("Target Close", _field(deal["target_close"]))
    d4.metric("Round", _field(deal["raise_round"]))

    st.caption(
        f"Success fee ≈ {sf_pct:.2f}% × {fmt_money_m(deal['size'])} = "
        f"{fmt_money_m(succ_m)}, plus {fmt_money_m(ret_m)} retainer (${ret_k:,.0f}K)."
    )
    if _field(deal["scope"]) != "—":
        st.caption(f"**Scope:** {deal['scope']}")

    st.divider()

    # -------------------------------------------------
    # BUYER / INVESTOR OUTREACH (CRM)
    # -------------------------------------------------
    st.subheader("🤝 Buyer / Investor Outreach")
    st.caption("Track each counterparty through the outreach funnel: "
               "Identified → Contacted → NDA → IOI → LOI.")

    cps = load_counterparties(deal["id"])

    fcols = st.columns(len(CP_STAGES))
    for i, sname in enumerate(CP_STAGES):
        cnt = int((cps["status"] == sname).sum()) if not cps.empty else 0
        fcols[i].metric(sname, cnt)

    if cps.empty:
        st.info("No buyers / investors added yet.")
    else:
        st.dataframe(
            cps[["name", "cp_type", "status", "indicative_value", "notes", "updated"]]
            .rename(columns={
                "name": "Counterparty",
                "cp_type": "Type",
                "status": "Stage",
                "indicative_value": "Indicative ($M)",
                "notes": "Notes",
                "updated": "Updated",
            }),
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("➕ Add buyer / investor"):
        n_name = st.text_input("Name", key="cp_name")
        n_type = st.selectbox("Type", CP_TYPES, key="cp_ctype")
        n_status = st.selectbox("Stage", CP_STAGES, key="cp_status")
        n_val = st.number_input(
            "Indicative value ($M)", min_value=0.0, value=0.0, step=5.0, key="cp_val"
        )
        n_notes = st.text_input("Notes", key="cp_notes")

        if st.button("Add to outreach list"):
            if n_name.strip() == "":
                st.error("Name required.")
            else:
                c.execute("""
                INSERT INTO counterparties
                    (deal_id, name, cp_type, status, indicative_value, notes, updated)
                VALUES (?,?,?,?,?,?,?)
                """, (
                    int(deal["id"]), n_name.strip(), n_type, n_status,
                    n_val, n_notes, str(datetime.date.today())
                ))
                conn.commit()
                for k in ["cp_name", "cp_ctype", "cp_status", "cp_val", "cp_notes"]:
                    st.session_state.pop(k, None)
                st.success(f"Added {n_name.strip()}.")
                st.rerun()

    if not cps.empty:
        with st.expander("✏️ Update / remove a counterparty"):
            names = cps["name"].tolist()
            sel = st.selectbox("Counterparty", names, key="cp_edit_sel")
            sel_row = cps[cps["name"] == sel].iloc[0]
            cur_status = sel_row["status"] if sel_row["status"] in CP_STAGES else CP_STAGES[0]
            new_status = st.selectbox(
                "New stage", CP_STAGES,
                index=CP_STAGES.index(cur_status), key="cp_edit_status"
            )
            u1, u2 = st.columns(2)
            if u1.button("Update stage"):
                c.execute(
                    "UPDATE counterparties SET status=?, updated=? WHERE id=?",
                    (new_status, str(datetime.date.today()), int(sel_row["id"]))
                )
                conn.commit()
                st.success("Stage updated.")
                st.rerun()
            if u2.button("Remove"):
                c.execute(
                    "DELETE FROM counterparties WHERE id=?", (int(sel_row["id"]),)
                )
                conn.commit()
                st.success("Removed.")
                st.rerun()

    st.divider()

    st.subheader("💰 Returns Analysis (MOIC / IRR)")
    st.caption(
        "First-pass sponsor returns. Adjust the exit assumptions below; debt is "
        "held flat (no amortization) to keep the mechanics transparent."
    )

    ra1, ra2, ra3 = st.columns(3)
    hold_years = ra1.slider("Hold period (yrs)", 1, 10, 5, key="ra_hold")
    # Default the exit multiple to the expected EV/EBITDA, clamped into the
    # slider's range (raises/advisory may have no multiple, so fall back to 8x).
    em_default = float(_num(deal["entry_multiple"]))
    if not (1.0 <= em_default <= 25.0):
        em_default = 8.0
    exit_multiple = ra2.slider(
        "Exit multiple (x)", 1.0, 25.0,
        em_default, step=0.5, key="ra_exit"
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
        if st.button("➡ Advance Engagement Stage"):

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