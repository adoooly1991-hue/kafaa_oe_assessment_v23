
import math

def _impact_midpoint(rng):
    try:
        a,b = float(rng[0]), float(rng[1])
        return max(0.0, (a+b)/2.0)/100.0
    except Exception:
        return 0.15

def _edge_factor_from_ratio(ratio):
    try:
        r = float(ratio)
    except Exception:
        return 1.0
    from math import log
    val = 1.0 + max(-0.4, min(0.4, log(r if r>0 else 1e-6)))
    return max(0.7, min(1.3, val))

def compute_edge_percentiles(templates, profile_key=None, measured=None, history=None):
    prio = templates.get("prioritization", {})
    metrics = prio.get("edge_metrics", {})
    prof = templates.get("profiles", {}).get(profile_key or "", {})
    bm = (prof.get("benchmarks", {}) if prof else {})
    edge = {}
    measured = measured or {}
    history = history or {}
    for waste, m in metrics.items():
        key = m.get("key")
        hib = bool(m.get("higher_is_better", True))
        target = bm.get(key)
        val = measured.get(key)
        if val is None or target is None:
            edge[waste] = 1.0
            continue
        ratio = (val/target) if hib else (target/max(val,1e-6))
        factor = _edge_factor_from_ratio(ratio)
        edge[waste] = max(0.7, min(1.4, factor))
    return edge

def compute_pace(vc_summary, savings, templates, objective_weights=None, profile_key=None, measured=None, history=None):
    prio = templates.get("prioritization", {})
    obj2w = prio.get("objective_to_waste", {})
    # Critical weights
    if not objective_weights:
        objective_weights = {o["id"]: o.get("weight",1.0) for o in prio.get("critical_objectives",[])}
    total_w = sum(objective_weights.values()) or 1.0
    obj_norm = {k: float(v)/total_w for k,v in objective_weights.items()}
    # Waste weights
    waste_weight = {}
    for obj, ow in obj_norm.items():
        for w, coef in obj2w.get(obj, {}).items():
            waste_weight[w] = waste_weight.get(w, 0.0) + ow*float(coef)
    # Present
    present = {}
    for row in (vc_summary or []):
        for w, sc in row.get("top3", []):
            present[w] = present.get(w, 0.0) + float(sc or 0.0)
    # Advantage
    by_waste = (savings or {}).get("by_waste", {}) if savings else {}
    # Edge
    edge = compute_edge_percentiles(templates, profile_key=profile_key, measured=measured, history=history)
    # Combine
    combined = {}
    for w in set(list(present.keys()) + list(by_waste.keys()) + list(waste_weight.keys())):
        sev = present.get(w, 0.0)/max(1.0, len(vc_summary))  # avg stage score 0..5
        ben = float(by_waste.get(w, 0.0))
        ww  = float(waste_weight.get(w, 0.0))
        combined[w] = (sev/5.0) * (1.0 + ww) * edge.get(w,1.0) * (math.log10(ben + 10.0))
    top_wastes = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    # Badge
    badge_min = prio.get("kpi_badge",{}).get("min_tracked", 4)
    weights = list(objective_weights.values()) or [1.0]
    med = sorted(weights)[len(weights)//2]
    tracked = sum(1 for v in weights if v >= med)
    badge = {"enabled": tracked >= badge_min, "tracked": tracked, "required": badge_min}
    return {"top_wastes": top_wastes, "waste_weight": waste_weight, "badge": badge, "edge": edge}

def propose_countermeasures(vc_summary, templates, savings=None, max_per_stage=3, profile_key=None, include_generic=True, pace=None):
    # Merge libraries
    counter_db = {}
    if include_generic:
        for w, arr in (templates.get("countermeasures", {}) or {}).items():
            counter_db.setdefault(w, []).extend(arr)
    if profile_key:
        prof_lib = (templates.get("countermeasures_profiles", {}) or {}).get(profile_key, {})
        for w, arr in (prof_lib or {}).items():
            counter_db.setdefault(w, []).extend(arr)

    currency = templates.get("assumptions",{}).get("currency","SAR")
    by_waste = (savings or {}).get("by_waste", {}) if savings else {}
    actions = []
    for row in (vc_summary or []):
        stage = row.get("stage_name","")
        conf = float(row.get("confidence",1.0))
        picks = sorted(row.get("top3", []), key=lambda x: x[1], reverse=True)[:3]
        for waste, sc in picks:
            lib = counter_db.get(waste, [])
            if not lib: 
                continue
            sorted_lib = sorted(lib, key=lambda c: ({"low":0,"medium":1,"high":2}.get(c.get("effort","medium"),1), -_impact_midpoint(c.get("impact_pct",[10,20]))))
            for cm in sorted_lib[:2]:
                potential = float(by_waste.get(waste, 0.0)) * _impact_midpoint(cm.get("impact_pct",[10,20])) * (sc/5.0) * conf
                priority = "Now" if cm.get("effort","low")=="low" and potential>0 else ("Next" if cm.get("effort")=="medium" else "Later")
                actions.append({
                    "stage": stage,
                    "waste": waste.lower(),
                    "action": cm.get("name",""),
                    "desc": cm.get("desc",""),
                    "effort": cm.get("effort","medium"),
                    "impact_pct_range": cm.get("impact_pct",[10,20]),
                    "est_annual_benefit": potential,
                    "est_annual_benefit_fmt": f"{potential:,.0f} {currency}",
                    "priority": priority,
                    "kpi": cm.get("kpi",""),
                    "preconditions": cm.get("pre","")
                })
        # cap per stage
        stage_items = [a for a in actions if a["stage"]==stage]
        stage_items = sorted(stage_items, key=lambda a: a["est_annual_benefit"], reverse=True)[:max_per_stage]
        actions = [a for a in actions if a["stage"]!=stage] + stage_items

    actions = sorted(actions, key=lambda a: a["est_annual_benefit"], reverse=True)
    # PACE weighting
    if pace and pace.get("top_wastes"):
        rank_map = {w: i+1 for i,(w,_) in enumerate(pace["top_wastes"])}
        for a in actions:
            r = rank_map.get(a["waste"], None)
            if r is not None:
                if r <= 2: a["priority"] = "Now"
                elif r <= 4 and a.get("priority") != "Now": a["priority"] = "Next"
                else: a["priority"] = a.get("priority","Later")
                a["est_annual_benefit"] *= (1.0 + max(0.0, 0.15*(max(0, 6 - r))))
                a["est_annual_benefit_fmt"] = f"{a['est_annual_benefit']:,.0f} {templates.get('assumptions',{}).get('currency','SAR')}"
    for i,a in enumerate(actions, start=1):
        a["rank"] = i
    return actions

def vc_stage_names():
    return [
        "Order Intake","Inbound Logistics","Receiving & QA","Raw Material Storage","Kitting/Pre‑production",
        "Production","Finishing/Pack","Outbound Logistics","Shipping/Customer"
    ]
