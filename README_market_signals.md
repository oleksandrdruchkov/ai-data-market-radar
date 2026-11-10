# Ринкові сигнали учасників перегонів (SEC EDGAR)

Два збирачі на спільному каркасі `core/`. Джерело - офіційні безкоштовні API SEC
(`data.sec.gov`), дані подані емітентами під юридичну відповідальність. LLM не потрібна,
квота Gemini не витрачається.

| Збирач | Таблиця | Що дає |
|---|---|---|
| `collectors/sec_financials.py` | `fct_lab_financials` | Квартали та роки: виручка, капвитрати (паливо обчислень), R&D, чистий прибуток/збиток, гроші на рахунках |
| `collectors/sec_filings.py` | `fct_lab_filings` | Стрічка подій: IPO (S-1, 424B4), повторні розміщення, 8-K з номерами пунктів, 13D/13G, DEF 14A, Форма 4 |

Подання: `v_lab_financials_quarterly`, `v_race_fuel_quarterly`, `v_lab_key_filings`.

## Учасники

`collectors/seeds/market_companies.json`: Alphabet, Meta, SpaceX (з xAI), Anthropic, Alibaba,
плюс Microsoft і Amazon (спонсори), Nvidia (постачальник). Новий учасник після IPO = один рядок.
Anthropic уже в списку: поки тикера `ANT` немає в реєстрі SEC, збирач його пропускає і пише це в лог.
`name_must_contain` захищає від чужої компанії з тим самим тикером.

## Встановлення

1. Файли покласти в репозиторій: `collectors/_sec_common.py`, `collectors/sec_financials.py`,
   `collectors/sec_filings.py`, `collectors/seeds/market_companies.json`, `tests/test_sec_common.py`.
2. SQL Editor → `sql/015_market_signals.sql` → Run.
3. GitHub → Settings → Secrets → новий секрет `SEC_USER_AGENT`, наприклад `Skynet radar ваша@пошта`.
   SEC вимагає назву й контакт у кожному запиті, інакше відповідає 403.
4. Рядки в `ops_sources` для `sec_financials` і `sec_filings` - так само, як для інших збирачів.
5. Крок у `.github/workflows/pipeline_cron.yml`:
   ```yaml
   - name: SEC financials
     env:
       SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
       SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
       SEC_USER_AGENT: ${{ secrets.SEC_USER_AGENT }}
     run: python -m collectors.sec_financials
   - name: SEC filings
     env:
       SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
       SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
       SEC_USER_AGENT: ${{ secrets.SEC_USER_AGENT }}
     run: python -m collectors.sec_filings
   ```
   Запускати раз на добу достатньо: звіти квартальні, 8-K - протягом 4 робочих днів після події.

## Що звірити з вашим каркасом

Код написано за інтерфейсом з `radar-core-migration.md` (`fetch` → `RawItem`, `parse` → dict).
Сам `core/` я не бачив, тому перевірте:
* чи `extraction_method` має обмеження на допустимі значення - якщо так, додайте `sec_xbrl` і `sec_submissions`;
* чи `parse` без виклику `self.llm` нормально проходить (за задумом так: LLM тут не потрібна);
* чи `radar_add_fact_columns` додає `event_date` - якщо ні, приберіть цей ключ з `parse`.

## Обмеження (чесно)

* **Консолідовані дані.** Капвитрати Alphabet включають увесь Google, SpaceX - ракети й Starlink.
  `v_race_fuel_quarterly` - верхня межа витрат, а не точна сума на ШІ. Розбивка за сегментами
  в API companyfacts відсутня; її можна витягати з тексту 10-Q через Gemini наступним кроком.
* **Alibaba** - іноземний емітент: лише річний 20-F, звітність у юанях (`currency = CNY`),
  тому в суму USD не потрапляє.
* **OpenAI, DeepSeek, Mistral** - не публічні, сліпа зона до лістингу.
* **Ціни акцій** SEC не публікує. Офіційні щоденні ціни продає Nasdaq; безкоштовні бібліотеки
  неофіційні. Тому ціни поки не збираються - це окреме рішення.
* Живого запуску проти SEC не було (у середовищі розробки доступ до sec.gov закритий);
  логіку перевірено тестами на зразкових даних у форматі SEC: `python -m pytest -q tests/test_sec_common.py`.
