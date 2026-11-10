"""
review_ui.py
Інтерфейс перевірки записів кола лідерів (підтвердити / відхилити / скасувати рішення).
Відкривається двома шляхами, щоб не залежати від того, чи Streamlit підхопив сторінку:
  * головна сторінка з параметром ?review=1 (app.py);
  * окрема сторінка pages/review.py.
Логіка рішень - core/review.py.

Streamlit Secrets: REVIEW_PASSWORD (без нього вхід вимкнено), SUPABASE_URL, SUPABASE_KEY.
"""

from __future__ import annotations

import os
import time

import pandas as pd
import streamlit as st

from core.db import Db
from core import review

MAX_ATTEMPTS = 5


def secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, os.getenv(name, default))
    except Exception:          # немає secrets.toml локально
        return os.getenv(name, default)


# ---------------- вхід ----------------

def login() -> bool:
    if st.session_state.get("review_ok"):
        return True
    expected = secret("REVIEW_PASSWORD")
    st.title("🔒 Перевірка записів")
    if not expected:
        st.error("Вхід вимкнено: у Secrets не задано REVIEW_PASSWORD.")
        return False
    attempts = st.session_state.get("review_attempts", 0)
    if attempts >= MAX_ATTEMPTS:
        st.error("Забагато невдалих спроб. Оновіть сторінку пізніше.")
        return False
    with st.form("login"):
        pwd = st.text_input("Пароль", type="password")
        if st.form_submit_button("Увійти"):
            if review.check_password(pwd, expected):
                st.session_state["review_ok"] = True
                st.rerun()
            st.session_state["review_attempts"] = attempts + 1
            time.sleep(2)              # уповільнюємо підбір
            st.error(f"Невірний пароль ({attempts + 1} з {MAX_ATTEMPTS}).")
    return False


@st.cache_resource
def _make_db() -> Db:
    from supabase import create_client
    url, key = secret("SUPABASE_URL"), secret("SUPABASE_KEY")
    if not url or not key:
        st.error("Немає SUPABASE_URL / SUPABASE_KEY у Secrets.")
        st.stop()
    return Db(client=create_client(url, key))


# ---------------- показ запису ----------------

def pct(x) -> str:
    return "—" if x is None or pd.isna(x) else f"{100 * float(x):.3f}%"


def show_items(title: str, items):
    if not items:
        return
    st.markdown(f"**{title}**")
    for it in items:
        sev = f", рівень {it['severity']}" if it.get("severity") is not None else ""
        n = f", n = {it['n']}" if it.get("n") is not None else ""
        st.markdown(f"- {it.get('category', '—')}{sev}{n} · с. {it.get('page', '—')}")
        if it.get("quote"):
            st.caption(f"«{it['quote']}»")
        if it.get("why"):
            st.caption(f"не враховано: {it['why']}")


def show_record(r: dict):
    st.markdown(
        f"**{r['lab']} · {r['model_name']}** · реліз {r.get('release_date') or '—'}  \n"
        f"Джерело: [{r.get('source_doc') or r['source_url']}]({r['source_url']}) · "
        f"розділ {r.get('section') or '—'} · сторінки {r.get('page') or '—'}"
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Поза межами", pct(r.get("rate_out")))
    c2.metric("Дій поза межами (n)", r.get("n_out") if r.get("n_out") is not None else "—")
    c3.metric("Вибірка (n)", r.get("n_total") if r.get("n_total") is not None else "—")
    c4.metric("Одиниця", r.get("unit") or "—")
    if r.get("evidence_quote"):
        st.caption(f"Цитата про вибірку: «{r['evidence_quote']}»")
    show_items("Враховано як дії поза межами", r.get("counted"))
    show_items("Не враховано", r.get("excluded"))
    log = r.get("verification_log") or []
    if log:
        with st.expander("Журнал автоматичної перевірки"):
            for line in log:
                st.markdown(f"- {line}")


def render(db: Db | None = None) -> None:
    """Уся сторінка перевірки. Викликається з app.py (?review=1) і з pages/review.py."""
    st.markdown("[← Назад до радара](./)")
    if not login():
        return
    db = db or _make_db()

    # ---------------- черга ----------------

    st.title("🔒 Перевірка записів кола лідерів")
    st.caption("Лише дані реального використання моделей. Симуляції й тести на коло не потрапляють і тут не показуються. "
               "Перед рішенням відкрийте джерело на вказаній сторінці й звірте числа та цитати.")

    if msg := st.session_state.pop("review_msg", None):
        st.success(msg)

    queue = review.pending(db)
    st.subheader(f"Чекають на рішення: {len(queue)}")
    if not queue:
        st.info("Черга порожня.")

    for r in queue:
        with st.container(border=True):
            show_record(r)
            comment = st.text_input("Коментар / причина відхилення", key=f"c{r['id']}")
            b1, b2, _ = st.columns([1, 1, 4])
            action = None
            if b1.button("✅ Підтвердити", key=f"a{r['id']}", use_container_width=True):
                action = ("approve", "підтверджено")
            if b2.button("❌ Відхилити", key=f"r{r['id']}", use_container_width=True):
                action = ("reject", "відхилено")
            if action:
                try:
                    if action[0] == "approve":
                        review.approve(db, r["id"], comment)
                    else:
                        review.reject(db, r["id"], comment)
                except Exception as e:
                    st.error(str(e))
                else:
                    st.session_state["review_msg"] = f"Запис {r['id']} {action[1]}."
                    st.cache_data.clear()   # головна сторінка одразу побачить зміни
                    st.rerun()

    # ---------------- останні рішення ----------------

    st.divider()
    st.subheader("Останні рішення людини")
    done = review.decided(db)
    if not done:
        st.caption("Ще немає.")
    for r in done:
        status = "✅ підтверджено" if r.get("verified") else "❌ відхилено"
        with st.expander(f"{status} · {r['lab']} · {r['model_name']} · {str(r.get('verified_at') or '')[:16]}"):
            show_record(r)
            if r.get("notes"):
                st.caption(r["notes"])
            if st.button("↩️ Скасувати рішення", key=f"u{r['id']}"):
                review.undo(db, r["id"])
                st.session_state["review_msg"] = f"Рішення щодо запису {r['id']} скасовано."
                st.cache_data.clear()
                st.rerun()

    st.divider()
    if st.button("Вийти"):
        st.session_state["review_ok"] = False
        st.rerun()
