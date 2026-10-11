"""Registry of st.Page objects so pages can link to each other with st.switch_page."""

from __future__ import annotations

import streamlit as st

_PAGES: dict[str, st.Page] = {}


def register(key: str, page: st.Page) -> st.Page:
    _PAGES[key] = page
    return page


def page(key: str) -> st.Page:
    return _PAGES[key]
