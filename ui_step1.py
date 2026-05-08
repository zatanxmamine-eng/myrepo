# ui_step1.py
import streamlit as st
from streamlit_folium import st_folium
from gee_utils import load_geojson, get_years, get_crop_types, get_varieties, filter_features
from map_utils import make_parcel_map, find_clicked_parcel

def render_step1(geojson_data):
    left, center, right = st.columns([1.5, 4, 1.5])

    # ── Filter panel ──
    with left:
        st.markdown("**กรองแปลง**")
        years = get_years(geojson_data)
        year = st.selectbox("📅 ปีการผลิต", years,
                            index=years.index(st.session_state.target_year) if st.session_state.target_year in years else 0)
        st.session_state.target_year = year

        crop_types = get_crop_types(geojson_data, year)
        crop_type = st.selectbox("🌾 ประเภทอ้อย", crop_types)

        varieties = get_varieties(geojson_data, year)
        variety = st.selectbox("🌱 พันธุ์อ้อย", varieties)

        areas = [f["properties"].get("AREA_RAI", 0) or 0 for f in geojson_data["features"]]
        area_min, area_max = int(min(areas)), int(max(areas))
        area_range = st.slider("📐 ขนาด (ไร่)", area_min, area_max, (area_min, area_max))

        search = st.text_input("🔍 ค้นหารหัส", "")

        filtered = filter_features(geojson_data, year, crop_type, variety, area_range[0], area_range[1], search)
        filtered_codes = {f["properties"]["FIELD_CODE"] for f in filtered}
        st.caption(f"แสดง {len(filtered_codes)} / 297 แปลง")

    # ── Map ──
    with center:
        m = make_parcel_map(geojson_data, filtered_codes, set(st.session_state.selected_fields))
        map_data = st_folium(m, width=700, height=450, returned_objects=["last_clicked"])

        # Handle click
        if map_data and map_data.get("last_clicked"):
            lat = map_data["last_clicked"]["lat"]
            lon = map_data["last_clicked"]["lng"]
            clicked_code = find_clicked_parcel(geojson_data, lat, lon)
            if clicked_code and clicked_code in filtered_codes:
                if clicked_code in st.session_state.selected_fields:
                    st.session_state.selected_fields.remove(clicked_code)
                else:
                    st.session_state.selected_fields.append(clicked_code)
                st.rerun()

    # ── Selected list ──
    with right:
        st.markdown(f"**เลือกแล้ว ({len(st.session_state.selected_fields)})**")
        if st.button("ล้างทั้งหมด", use_container_width=True):
            st.session_state.selected_fields = []
            st.rerun()

        ct_col = f"CT_{year.replace('-', '_')}"
        props_map = {f["properties"]["FIELD_CODE"]: f["properties"] for f in geojson_data["features"]}

        for code in list(st.session_state.selected_fields):
            p = props_map.get(code, {})
            area = p.get("AREA_RAI", "?")
            ct = p.get(ct_col, "?")
            col_a, col_b = st.columns([4, 1])
            with col_a:
                st.markdown(f"<small style='color:#4ade80'><b>{code}</b><br>{area} ไร่ · {ct}</small>", unsafe_allow_html=True)
            with col_b:
                if st.button("✕", key=f"del_{code}"):
                    st.session_state.selected_fields.remove(code)
                    st.rerun()

        st.divider()
        if st.session_state.selected_fields:
            if st.button("ถัดไป →", type="primary", use_container_width=True):
                st.session_state.step = 2
                st.rerun()
        else:
            st.caption("เลือกแปลงบนแผนที่ก่อน")
