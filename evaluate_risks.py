import os
import numpy as np
from scipy import stats
from supabase import create_client, Client
from datetime import datetime, timezone

# 1. МАТЕМАТИЧНЕ ЯДРО MONTE CARLO
Z = {"IQR_50": 1.35, "CI_90": 3.29, "CI_95": 3.92}

def _sigma_log(lo, hi, kind):
    if kind not in Z:
        raise ValueError(f"interval_type must be one of {list(Z)}")
    return (np.log(hi) - np.log(lo)) / Z[kind]

def run_pathway_monte_carlo(
    t50_obs, t50_ci, c_obs, n_tasks, thr, *,
    interval_type="CI_90", t80_obs=None, t80_ci=None, t50_censored=False,
    ceiling=16.0, sigma_elicit=0.35, sigma_c=0.05,
    s_prior=(0.85, 0.15), s_bounds=(0.5, 1.5), corr=0.85,
    p_rule=0.10, n_iter=10000, seed=42,
):
    rng = np.random.default_rng(seed)
    delta = np.abs(rng.normal(0, sigma_elicit, n_iter)) if sigma_elicit > 0 else np.zeros(n_iter)

    def trunc(mu, sd, lo, hi):
        if sd == 0: return np.full(n_iter, mu)
        return stats.truncnorm.rvs((lo - mu) / sd, (hi - mu) / sd, loc=mu, scale=sd, size=n_iter, random_state=rng)

    sigma_50 = _sigma_log(*t50_ci, interval_type) if t50_ci[0] != t50_ci[1] else 0.0

    if t50_censored:
        sigma_80 = _sigma_log(*t80_ci, interval_type) if t80_ci and t80_ci[0] != t80_ci[1] else 0.0
        s_cap = np.log(4) / np.log(t50_obs / t80_obs)
        s = trunc(s_prior[0], s_prior[1], s_bounds[0], min(s_bounds[1], s_cap))
        eps_80 = rng.normal(0, sigma_80, n_iter) if sigma_80 > 0 else np.zeros(n_iter)
        t80 = np.exp(np.log(t80_obs) + eps_80 + delta)
        t50_unbounded = np.maximum(t80 * 4 ** (1 / s), t50_obs)
    else:
        if t80_obs and t80_ci:
            sigma_80 = _sigma_log(*t80_ci, interval_type) if t80_ci[0] != t80_ci[1] else 0.0
            z1, z2, z3 = rng.normal(0, 1, n_iter), rng.normal(0, 1, n_iter), rng.normal(0, 1, n_iter)
            eps_50 = sigma_50 * (np.sqrt(corr) * z1 + np.sqrt(1 - corr) * z2) if sigma_50 > 0 else np.zeros(n_iter)
            eps_80 = sigma_80 * (np.sqrt(corr) * z1 + np.sqrt(1 - corr) * z3) if sigma_80 > 0 else np.zeros(n_iter)
            t50_unbounded = np.exp(np.log(t50_obs) + eps_50 + delta)
            t80 = np.minimum(np.exp(np.log(t80_obs) + eps_80 + delta), t50_unbounded * 0.99)
        else:
            eps_50 = rng.normal(0, sigma_50, n_iter) if sigma_50 > 0 else np.zeros(n_iter)
            t50_unbounded = np.exp(np.log(t50_obs) + eps_50 + delta)
            s = trunc(*s_prior, *s_bounds)
            t80 = t50_unbounded * 4 ** (-1 / s)

    if sigma_c == 0:
        c = np.full(n_iter, c_obs)
    else:
        c = np.clip(rng.beta(n_tasks * c_obs + 1, n_tasks * (1 - c_obs) + 1, n_iter) + np.abs(rng.normal(0, sigma_c, n_iter)), 0.0, 1.0)

    t50_gate = np.minimum(t50_unbounded, ceiling)
    tier = np.ones(n_iter, dtype=int)
    for j in (2, 3, 4):
        ok = np.ones(n_iter, dtype=bool)
        for key, x in (("c", c), ("t50", t50_gate), ("t80", t80)):
            need = thr.get(f"{key}_cri{j}")
            if need is not None: ok &= (x >= need)
        tier = np.where(ok, j, tier)

    p = {j: float(np.mean(tier >= j)) for j in (2, 3, 4)}
    not_assessable = [4] if (thr.get("t50_cri4") or 0) > ceiling else []
    for j in not_assessable: p[j] = None
    assigned = max([1] + [j for j, v in p.items() if v is not None and v >= p_rule])

    return assigned, p[3], p[4], bool(not_assessable)

# 2. ІНТЕГРАЦІЯ З SUPABASE ТА GITHUB SECRETS
def process_and_save():
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
    SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Missing Supabase credentials.")

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    mc_config = supabase.table("dim_mc_parameters").select("*").eq("config_id", 1).execute().data[0]
    raw_thresholds = supabase.table("dim_cri_thresholds").select("*").execute().data
    thr_by_pathway = {row['pathway']: row for row in raw_thresholds}
    
    horizons = supabase.table("fct_metr_horizons").select("*").eq("is_synthetic", False).execute().data
    if not horizons: return

    output_rows = []
    for h_row in horizons:
        model_name = h_row['model_name']
        caps = supabase.table("fct_pathway_capabilities").select("*").eq("model_name", model_name).eq("is_synthetic", False).execute().data
        
        for c_row in caps:
            pathway = c_row['pathway']
            if pathway not in thr_by_pathway: continue
            
            t50_ci = (float(h_row['t50_lower']), float(h_row['t50_upper']))
            t80_ci = (float(h_row['t50_lower']), float(h_row['t50_upper'])) if h_row.get('t80_obs') else None
            
            assigned, p3, p4, is_sat = run_pathway_monte_carlo(
                t50_obs=float(h_row['t50_obs']), t50_ci=t50_ci,
                interval_type=h_row['interval_type'] or "CI_90",
                c_obs=float(c_row['c_score']), n_tasks=int(c_row['n_tasks']),
                thr=thr_by_pathway[pathway],
                t80_obs=float(h_row['t80_obs']) if h_row.get('t80_obs') else None, t80_ci=t80_ci,
                t50_censored=bool(h_row['is_censored']),
                ceiling=float(mc_config['metr_ceiling_hours']), sigma_elicit=float(mc_config['sigma_elicit']),
                sigma_c=float(mc_config['sigma_c']), corr=float(mc_config['t50_t80_correlation']),
                p_rule=float(mc_config['p_rule'])
            )
            
            output_rows.append({
                "model_name": model_name, "pathway": pathway,
                "assigned_tier": assigned, "prob_cri3": p3, "prob_cri4": p4, "is_saturated": is_sat,
                "updated_at": datetime.now(timezone.utc).isoformat()
            })

    if output_rows:
        supabase.table("fct_risk_profiles").upsert(output_rows, on_conflict="model_name,pathway").execute()
        print(f"Successfully evaluated and saved {len(output_rows)} pathway profiles.")

if __name__ == "__main__":
    process_and_save()
