"""Forward P/E Investment Dashboard.

Run:  streamlit run app.py
Philosophy: Price = Forward EPS x Forward P/E. Forecast the earnings, judge the multiple.
"""
import streamlit as st

st.set_page_config(page_title="Forward P/E Dashboard", page_icon="📈", layout="wide")

from views.common import bootstrap_secrets  # noqa: E402

bootstrap_secrets()  # API keys from the website's secrets settings

pages = st.navigation([
    st.Page("views/dashboard.py", title="Stock dashboard", icon="📈", default=True),
    st.Page("views/watchlist.py", title="Watchlist", icon="⭐"),
])
pages.run()
