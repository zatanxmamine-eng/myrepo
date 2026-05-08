# app.py
import streamlit as st
from gee_utils import load_geojson, init_gee
from ui_step1 import render_step1
from ui_step2 import render_step2
from ui_step3 import render_step3

st.set_page_config(page_title="🌾 GEE Sugarcane Analyzer", layout="wide")

@st.cache_resource
def setup_gee():
    init_gee()
    return True

setup_gee()
geojson_data = load_geojson()

for key, val in [
    ("step", 1),
    ("selected_fields", []),
    ("target_year", "65-66"),
    ("analyses", []),
    ("results", {}),
    ("active_result_tab", "🗺️ แผนที่รวม"),
]:
    if key not in st.session_state:
        st.session_state[key] = val

# Step indicator
cols = st.columns(3)
labels = ["① เลือกแปลง", "② เลือกการวิเคราะห์", "③ ดูผลลัพธ์"]
for i, (col, label) in enumerate(zip(cols, labels), 1):
    with col:
        if st.session_state.step == i:
            st.markdown(f"<div style='background:#2563eb;color:white;padding:8px;border-radius:6px;text-align:center;font-weight:bold'>{label}</div>", unsafe_allow_html=True)
        elif st.session_state.step > i:
            st.markdown(f"<div style='background:#14532d;color:#4ade80;padding:8px;border-radius:6px;text-align:center'>✅ {label}</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div style='background:#1f2937;color:#6b7280;padding:8px;border-radius:6px;text-align:center'>{label}</div>", unsafe_allow_html=True)

st.divider()

# Routing
if st.session_state.step == 1:
    render_step1(geojson_data)
elif st.session_state.step == 2:
    render_step2()
elif st.session_state.step == 3:
    render_step3(geojson_data)
