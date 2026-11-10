"""
pages/review.py
Окрема сторінка перевірки. Уся логіка - review_ui.py (та сама, що й на головній з ?review=1).
"""

import streamlit as st

st.set_page_config(page_title="Перевірка записів", page_icon="🔒", layout="wide")

import review_ui  # noqa: E402

review_ui.render()
