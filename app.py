
import streamlit as st
import pandas as pd
import yaml
from engine import compute_pace, propose_countermeasures, vc_stage_names
from report import export_pptx

st.set_page_config(page_title="OE Assessment Report Generator — v23", layout="wide")

# Load templates
with open("templates.yaml","r",encoding="utf-8") as f:
    templates = yaml.safe_load(f)

st.title("OE Assessment Report Generator")
# Language & profile
lang = st.sidebar.selectbox("Language", ["en","ar"], format_func=lambda x: "English" if x=="en" else "العربية", key="lang")
i18n_pace = templates.get("i18n",{}).get("pace",{}).get(lang, templates.get("i18n",{}).get("pace",{}).get("en", {}))
profile_key = st.sidebar.selectbox("Industry profile", list(templates.get("profiles",{}).keys()), format_func=lambda k: templates["profiles"][k]["label"], key="profile_key")
st.session_state["profile_key"] = profile_key
st.session_state["profile"] = templates["profiles"][profile_key]
brand_primary = st.sidebar.color_picker("Brand color", "#C00000")

nav = st.radio("Go to", ["Welcome","Value Chain","Business Case","Kafaa PACE","Countermeasures","Export"], index=0, key="nav")

if st.session_state["nav"] == "Welcome":
    st.markdown("### Welcome")
    st.write("This minimal v23 bundle includes Kafaa PACE with Edge percentiles, PACE-weighted countermeasures, Arabic labels, and PPTX export (PACE + Action Plan).")

elif st.session_state["nav"] == "Value Chain":
    st.subheader("Value Chain — severity by waste per stage")
    stages = vc_stage_names()
    wastes = ["defects","waiting","inventory","transportation","motion","overprocessing","overproduction","safety"]
    vc_rows = []
    for sname in stages:
        with st.expander(f"{sname}"):
            scores = {}
            cols = st.columns(4)
            for i, w in enumerate(wastes):
                with cols[i%4]:
                    scores[w] = st.slider(f"{w.title()} severity", 0.0, 5.0, 0.0, 0.5, key=f"{sname}-{w}")
            conf = st.slider("Confidence", 0.1, 1.0, 0.8, 0.05, key=f"{sname}-conf")
            # pick top3
            top3 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
            vc_rows.append({"stage_name": sname, "top3": top3, "confidence": conf})
    st.session_state["vc_summary"] = vc_rows
    st.success("Value Chain signals captured.")

elif st.session_state["nav"] == "Business Case":
    st.subheader("Business Case — estimated annual benefit by waste")
    wastes = ["defects","waiting","inventory","transportation","motion","overprocessing","overproduction","safety"]
    by_waste = {}
    cols = st.columns(4)
    for i,w in enumerate(wastes):
        with cols[i%4]:
            by_waste[w] = st.number_input(f"{w.title()} (SAR)", value=0.0, step=1000.0, key=f"bc-{w}")
    total = sum(by_waste.values())
    st.metric("Total Estimated Benefit (annual)", f"{total:,.0f} {templates.get('assumptions',{}).get('currency','SAR')}")
    st.session_state["savings"] = {"by_waste": by_waste, "total": total}

elif st.session_state["nav"] == "Kafaa PACE":
    st.subheader(i18n_pace.get("title","Kafaa PACE — Prioritization Engine"))
    st.caption("Present • Advantage • Critical • Edge")
    prio = templates.get("prioritization", {})
    # Critical — objective weights
    st.markdown(f"### {i18n_pace.get('critical','Critical — choose what matters most now')}")
    cols = st.columns(6)
    obj_weights = {}
    labels = i18n_pace.get("objectives",{})
    for i, obj in enumerate(prio.get("critical_objectives", [])):
        with cols[i%6]:
            label = labels.get(obj["id"], obj["name"])
            obj_weights[obj["id"]] = st.slider(label, 0.0, 2.0, float(obj.get("weight",1.0)), 0.1, key=f"pace-obj-{obj['id']}")
    st.session_state["pace_objectives"] = obj_weights

    # Present preview
    st.markdown(f"### {i18n_pace.get('present','Present — baseline signals')}")
    vc_summary = st.session_state.get("vc_summary", [])
    if not vc_summary:
        st.info("Fill the Value Chain page first.")
    else:
        for row in vc_summary[:4]:
            tops = ", ".join([f"{w.title()} ({sc:.1f})" for w,sc in row.get("top3",[])])
            st.write(f"**{row['stage_name']}** → {tops}  | Confidence: {row.get('confidence',1.0):.0%}")

    # Advantage preview
    st.markdown(f"### {i18n_pace.get('advantage','Advantage — estimated annual benefit')}")
    savings = st.session_state.get("savings", {})
    if not savings:
        st.info("Enter values in Business Case.")
    else:
        bw = savings.get("by_waste", {})
        st.write({k: f"{v:,.0f}" for k,v in bw.items()})
        st.metric("Total Estimated Benefit (annual)", f"{savings.get('total',0.0):,.0f}")

    # Edge measured
    st.markdown("##### Enter measured values (optional) for better percentile matching")
    em = {}
    edge_map = prio.get("edge_metrics",{})
    cols2 = st.columns(3)
    i2 = 0
    for w, cfg in edge_map.items():
        with cols2[i2%3]:
            key = cfg.get("key"); unit = cfg.get("unit","")
            em[key] = st.number_input(f"{key} ({unit})", value=0.0, step=0.1, key=f"pace-meas-{key}")
        i2 += 1
    st.session_state["pace_measured"] = em

    pace = compute_pace(vc_summary, savings, templates,
                        objective_weights=obj_weights if obj_weights else None,
                        profile_key=st.session_state.get("profile_key"),
                        measured=st.session_state.get("pace_measured"),
                        history=st.session_state.get("pace_history"))
    st.session_state["pace"] = pace

    st.markdown(f"### {i18n_pace.get('edge','Edge — combined priority (top themes)')}")
    topw = pace.get("top_wastes", [])[:6]
    st.write([f"{w.title()}" for w,_ in topw])
    badge = pace.get("badge", {})
    st.progress(min(1.0, badge.get("tracked",0)/max(1, badge.get("required",4))))
    st.caption(f"{i18n_pace.get('badge','Kafaa Readiness Badge progress')}: {badge.get('tracked',0)}/{badge.get('required',4)}")

elif st.session_state["nav"] == "Countermeasures":
    st.subheader("Countermeasures & Action Plan")
    vc_summary = st.session_state.get("vc_summary", [])
    savings = st.session_state.get("savings", {})
    max_stage = st.slider("Max actions per stage", 1, 5, 3)
    include_generic = st.checkbox("Include generic actions", True)
    actions = propose_countermeasures(vc_summary, templates, savings=savings, max_per_stage=max_stage,
                                      profile_key=st.session_state.get("profile_key"), include_generic=include_generic,
                                      pace=st.session_state.get("pace"))
    if actions:
        df = pd.DataFrame(actions)
        st.session_state["actions_df"] = df
        st.dataframe(df[["rank","priority","stage","waste","action","effort","kpi","est_annual_benefit_fmt","desc","preconditions"]], use_container_width=True)
        st.metric("Total potential (top items)", f"{df['est_annual_benefit'].sum():,.0f}")
    else:
        st.info("Provide Value Chain, Business Case, and PACE inputs.")

elif st.session_state["nav"] == "Export":
    st.subheader("Export — PPTX")
    actions_df = st.session_state.get("actions_df")
    pace = st.session_state.get("pace", {})
    fname = st.text_input("File name", "kafaa_oe_assessment_v23.pptx")
    if st.button("Generate PPTX"):
        out_path = fname
        try:
            export_pptx(out_path, pace=pace, actions_df=actions_df, brand_primary=brand_primary, logo_path=None)
            with open(out_path, "rb") as f:
                st.download_button("Download PPTX", f, file_name=fname, mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")
            st.success("PPTX generated.")
        except Exception as e:
            st.error(f"Export failed: {e}")
