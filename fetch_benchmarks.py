def process_and_ingest():
    raw_data = fetch_live_data()
    
    if not raw_data:
        logging.error("Live feeds unavailable. Aborting ingestion to maintain data integrity.")
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    parsed_models = []

    for item in raw_data:
        name = str(item.get("model", item.get("model_name", ""))).strip()
        if not name:
            continue

        try:
            elo = float(item.get("rating", item.get("arena_elo", 0.0)))
        except (ValueError, TypeError):
            continue

        # Відсікаємо застарілі або слабкі моделі нижче базового рівня
        if elo < 1200.0:
            continue

        try:
            coding = float(item.get("coding", item.get("coding_score", 80.0)))
        except (ValueError, TypeError):
            coding = 80.0

        try:
            hard = float(item.get("hard_prompts", item.get("hard_prompts_score", 80.0)))
        except (ValueError, TypeError):
            hard = 80.0

        org = item.get("organization", item.get("org", "Independent Lab"))
        license_type = item.get("license", "Proprietary" if "open" not in str(item).lower() else "Open Weights")

        parsed_models.append({
            "recorded_at": now_iso,
            "model_name": name,
            "organization": org,
            "arena_elo": round(elo, 1),
            "coding_score": round(coding, 1),
            "hard_prompts_score": round(hard, 1),
            "defense_score": round(coding * 0.5 + hard * 0.5, 1),
            "license": license_type
        })

    if not parsed_models:
        logging.warning("No valid frontier models found in feed.")
        return

    # Сортуємо виключно за балами: від найсильнішої до найслабшої
    parsed_models.sort(key=lambda x: x["arena_elo"], reverse=True)

    # Залишаємо по 1 флагману від кожної організації серед топ-моделей
    unique_org_leaders = {}
    for m in parsed_models:
        org_key = m["organization"].lower()
        if org_key not in unique_org_leaders:
            unique_org_leaders[org_key] = m

    records = list(unique_org_leaders.values())[:8]

    logging.info(f"Submitting {len(records)} dynamically discovered models to Supabase...")
    res = supabase.table("fct_ai_benchmarks").insert(records).execute()
    count = len(res.data) if res.data else 0
    logging.info(f"Successfully inserted {count} frontier entries into fct_ai_benchmarks.")
