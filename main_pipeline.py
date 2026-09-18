name: Scheduled Data & AI Intelligence Pipeline

on:
  schedule:
    # Запуск щодня о 03:00 UTC, як ми визначили для нічного крону
    - cron: '0 3 * * *'
  # Можливість запустити вручну з кнопки в GitHub Actions
  workflow_dispatch:

jobs:
  run-pipeline:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests google-genai supabase pandas

      - name: Run Market Vacancies Pipeline (Adzuna + Custom Scrapers + Gemini)
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          ADZUNA_APP_ID: ${{ secrets.ADZUNA_APP_ID }}
          ADZUNA_APP_KEY: ${{ secrets.ADZUNA_APP_KEY }}
        run: |
          # main_pipeline керує збором для US, UK, APAC та парсингом Gemini
          python main_pipeline.py

      - name: Run DeepSeek Scraper
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          # Автоматичний запуск скрипта для збору китайських вакансій та їх перекладу
          python collector_deepseek.py

      - name: Refresh AI Benchmarks
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
        run: |
          python fetch_benchmarks.py