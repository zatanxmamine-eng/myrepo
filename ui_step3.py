# ui_step3.py
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from shapely.geometry import shape
from gee_utils import run_all

RESULT_TABS = [
    "🗺️ แผนที่รวม", "🌱 SAVI/NDWI", "🚀 Growth Speed",
    "🔄 Delta NDVI", "🗺️ Classification", "🌧️ CHIRPS",
    "📊 vs ผลผลิต (AY)", "📅 เปรียบข้ามปี", "🌾 เปรียบประเภท",
    "🚨 แปลงเสี่ยง", "🍃 NDRE",
]


def run_analysis(geojson_data):
    """Run GEE for all selected parcels, show progress"""
    fields = st.session_state.selected_fields
    year = st.session_state.target_year
    analyses = st.session_state.analyses

    results = {}
    progress = st.progress(0, text="กำลังวิเคราะห์...")
    status_box = st.empty()

    for i, field_code in enumerate(fields):
        status_box.info(f"🛰 กำลังวิเคราะห์แปลง {field_code} ({i+1}/{len(fields)})")
        try:
            results[field_code] = run_all(geojson_data, field_code, year, analyses)
        except Exception as e:
            results[field_code] = {"FIELD_CODE": field_code, "STATUS": f"Error: {e}"}
        progress.progress((i + 1) / len(fields), text=f"เสร็จ {i+1}/{len(fields)}")

    status_box.success(f"✅ วิเคราะห์เสร็จ {len(results)} แปลง")
    return results


def render_step3(geojson_data):
    # Run GEE when no results yet
    if not st.session_state.results:
        st.session_state.results = run_analysis(geojson_data)
        st.rerun()

    results = st.session_state.results
    df = pd.DataFrame(list(results.values()))

    nav, main = st.columns([1, 4])
    with nav:
        _render_nav(df)
    with main:
        _render_result(df, geojson_data)


def _render_nav(df):
    st.markdown("**ผลลัพธ์**")
    for tab in RESULT_TABS:
        is_active = st.session_state.active_result_tab == tab
        btn_type = "primary" if is_active else "secondary"
        if st.button(tab, key=f"nav_{tab}", use_container_width=True, type=btn_type):
            st.session_state.active_result_tab = tab
            st.rerun()

    st.divider()
    csv = df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button("📥 Export CSV", csv, "sugarcane_results.csv", "text/csv", use_container_width=True)

    if st.button("🗂️ Export GeoTIFF", use_container_width=True):
        from gee_utils import export_geotiff, load_geojson
        gj = load_geojson()
        tasks_started = 0
        for code in st.session_state.selected_fields:
            t = export_geotiff(gj, code, st.session_state.target_year)
            if t:
                tasks_started += 1
        st.success(f"ส่ง {tasks_started} tasks ไป GEE แล้ว → ดูผลใน Google Drive/GEE_SugarcaneExports/")

    if st.button("← เริ่มใหม่", use_container_width=True):
        st.session_state.step = 1
        st.session_state.selected_fields = []
        st.session_state.results = {}
        st.rerun()


def _render_result(df, geojson_data):
    tab = st.session_state.active_result_tab
    if tab == "🗺️ แผนที่รวม":
        _render_overview(df, geojson_data)
    elif tab == "🌱 SAVI/NDWI":
        _render_savi_table(df)
    elif tab == "🚨 แปลงเสี่ยง":
        _render_alerts(df)
    elif tab == "📊 vs ผลผลิต (AY)":
        _render_ay_compare(df, geojson_data)
    elif tab == "🌾 เปรียบประเภท":
        _render_crop_compare(df)
    elif tab == "📅 เปรียบข้ามปี":
        _render_year_compare(df, geojson_data)
    else:
        cols = [c for c in df.columns if c != "chirps_weekly"]
        st.dataframe(df[cols], use_container_width=True, hide_index=True)
        st.caption(f"ข้อมูลดิบสำหรับ {tab}")


def _render_overview(df, geojson_data):
    # Alert banner
    risk_df = df[df["STATUS"].str.contains("🔴|🟠", na=False)] if "STATUS" in df.columns else pd.DataFrame()
    if not risk_df.empty:
        codes = ", ".join(risk_df["FIELD_CODE"].tolist())
        st.error(f"🚨 พบ {len(risk_df)} แปลงเสี่ยง: {codes}")

    # Summary cards
    c1, c2, c3, c4 = st.columns(4)
    savi_avg = df["SAVI_mean"].mean() if "SAVI_mean" in df.columns else None
    good_avg = df["Good_pct"].mean() if "Good_pct" in df.columns else None
    c1.metric("SAVI เฉลี่ย", f"{savi_avg:.3f}" if savi_avg is not None else "N/A")
    c2.metric("งอกดี เฉลี่ย", f"{good_avg:.1f}%" if good_avg is not None else "N/A")
    c3.metric("แปลงเสี่ยง", len(risk_df))
    c4.metric("แปลงทั้งหมด", len(df))

    # Map
    status_color = {
        "🟢 งอกดี": "#00aa00", "🟡 ปานกลาง": "#ffdd00",
        "🟠 น้อย": "#ff6600", "🔴 ไม่งอก": "#dd0000",
    }
    selected_codes = df["FIELD_CODE"].tolist()
    first_feat = next((f for f in geojson_data["features"] if f["properties"]["FIELD_CODE"] in selected_codes), None)
    if first_feat:
        c = shape(first_feat["geometry"]).centroid
        center = [c.y, c.x]
    else:
        center = [15.0, 102.0]

    m = folium.Map(location=center, zoom_start=13, tiles="CartoDB dark_matter")
    result_map = {r["FIELD_CODE"]: r for r in df.to_dict("records")}

    for f in geojson_data["features"]:
        code = f["properties"]["FIELD_CODE"]
        if code not in result_map:
            continue
        r = result_map[code]
        color = status_color.get(r.get("STATUS", ""), "#374151")
        tip = f"{code} · {r.get('STATUS', '?')} · SAVI={r.get('SAVI_mean', 'N/A')}"
        folium.GeoJson(f, style_function=lambda x, c=color: {
            "color": c, "weight": 2, "fillColor": c, "fillOpacity": 0.45
        }, tooltip=tip).add_to(m)

    st_folium(m, width=800, height=380)

    # Summary table
    st.subheader("สรุปรายแปลง")
    show_cols = [c for c in ["FIELD_CODE", "AREA_RAI", "CROP_TYPE", "SAVI_mean", "Good_pct", "GrowthSpeed", "STATUS"] if c in df.columns]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)


def _render_savi_table(df):
    st.subheader("🌱 SAVI / NDWI / NDRE")
    cols = [c for c in ["FIELD_CODE", "SAVI_mean", "SAVI_sd", "NDWI_mean", "NDRE_mean", "Good_pct", "Poor_pct", "Dry_pct", "STATUS"] if c in df.columns]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)
    if "SAVI_mean" in df.columns:
        from chart_utils import chart_savi_bar
        st.plotly_chart(chart_savi_bar(df), use_container_width=True)


def _render_alerts(df):
    st.subheader("🚨 แปลงเสี่ยง")
    risk = df[df["STATUS"].str.contains("🔴|🟠", na=False)] if "STATUS" in df.columns else pd.DataFrame()
    if risk.empty:
        st.success("✅ ไม่พบแปลงเสี่ยงในชุดที่วิเคราะห์")
        return
    for _, row in risk.iterrows():
        with st.expander(f"{row['STATUS']} — {row['FIELD_CODE']} ({row.get('AREA_RAI', '?')} ไร่)"):
            st.write(f"SAVI: {row.get('SAVI_mean', 'N/A')} | งอกดี: {row.get('Good_pct', 'N/A')}% | ดินแห้ง: {row.get('Dry_pct', 'N/A')}%")
            speed = row.get("GrowthSpeed")
            if speed and speed > 0.003:
                st.warning("⚠️ Growth Speed สูงผิดปกติ — อาจมีวัชพืช")


def _render_ay_compare(df, geojson_data):
    st.subheader("📊 SAVI vs ผลผลิตจริง (AY)")
    if "SAVI_mean" not in df.columns:
        st.info("ต้องเลือก SAVI/NDWI ด้วย")
        return
    from chart_utils import chart_ay_scatter
    st.plotly_chart(chart_ay_scatter(df, geojson_data, st.session_state.target_year), use_container_width=True)


def _render_crop_compare(df):
    st.subheader("🌾 เปรียบตามประเภทอ้อย")
    if "SAVI_mean" not in df.columns or "CROP_TYPE" not in df.columns:
        st.info("ต้องมีข้อมูล SAVI_mean")
        return
    from chart_utils import chart_crop_boxplot
    st.plotly_chart(chart_crop_boxplot(df), use_container_width=True)


def _render_year_compare(df, geojson_data):
    st.subheader("📅 เปรียบข้ามปี")
    if df.empty:
        st.info("ไม่มีข้อมูล")
        return
    field = st.selectbox("เลือกแปลง", df["FIELD_CODE"].tolist(), key="yc_field")
    if st.button("📅 ดึงข้อมูลข้ามปี", key="yc_run"):
        from gee_utils import run_year_compare, load_geojson
        gj = load_geojson()
        with st.spinner(f"กำลังดึงข้อมูลข้ามปีสำหรับ {field}..."):
            res = run_year_compare(gj, field)
        from chart_utils import chart_year_compare
        st.plotly_chart(chart_year_compare(res["year_compare"], field), use_container_width=True)
        data_rows = [{"ปี": yr, "SAVI_mean": val} for yr, val in res["year_compare"].items()]
        st.dataframe(data_rows, use_container_width=True)
