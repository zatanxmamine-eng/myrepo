# ui_step2.py
import streamlit as st

ANALYSES = [
    ("savi",       "🌱 SAVI/NDWI สรุปภาพรวม",        2, True),
    ("growth",     "🚀 Growth Speed",                  1, True),
    ("delta_ndvi", "🔄 Delta NDVI",                    2, True),
    ("classify",   "🗺️ Classification 4 ระดับ",        1, True),
    ("chirps",     "🌧️ CHIRPS Rainfall รายสัปดาห์",    2, True),
    ("ndre",       "🍃 NDRE (Red Edge)",               0, True),
    ("ay_compare", "📊 SAVI vs ผลผลิตจริง (AY)",        0, False),
    ("year_comp",  "📅 เปรียบข้ามปี",                  3, True),
    ("crop_comp",  "🌾 เปรียบตามประเภทอ้อย",            0, False),
    ("alerts",     "🚨 แจ้งเตือนแปลงเสี่ยง",            0, False),
]

def render_step2():
    left, right = st.columns([3, 1])

    with left:
        st.markdown("**เลือกการวิเคราะห์** (เลือกได้หลายอย่าง)")
        selected = []
        for key, label, secs, needs_gee in ANALYSES:
            default = key in (st.session_state.analyses or ["savi", "growth"])
            checked = st.checkbox(label, value=default, key=f"ana_{key}")
            if checked:
                selected.append(key)
                tag = f"⏱ ~{secs} วิ/แปลง (batch)" if secs > 0 else "⚡ เร็ว (local)"
                gee_tag = "🛰 GEE" if needs_gee else "📊 local"
                st.caption(f"  {tag} · {gee_tag}")
        st.session_state.analyses = selected

    with right:
        n_parcels = len(st.session_state.selected_fields)
        gee_analyses = [(k, s) for k, _, s, g in ANALYSES if k in selected and g and s > 0]
        total_secs = sum(s for _, s in gee_analyses) * n_parcels

        st.markdown("**สรุป**")
        st.metric("การวิเคราะห์", len(selected))
        st.metric("จำนวนแปลง", n_parcels)
        if total_secs < 60:
            time_str = f"~{total_secs} วิ"
        else:
            time_str = f"~{total_secs // 60} นาที {total_secs % 60} วิ"
        st.metric("เวลาประมาณ", time_str)

        st.divider()
        if st.button("← ย้อนกลับ", use_container_width=True):
            st.session_state.step = 1
            st.rerun()
        if selected:
            if st.button("▶ วิเคราะห์", type="primary", use_container_width=True):
                st.session_state.step = 3
                st.rerun()
        else:
            st.caption("เลือกอย่างน้อย 1 การวิเคราะห์")
