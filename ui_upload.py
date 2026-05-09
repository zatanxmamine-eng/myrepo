# ui_upload.py
import json
import streamlit as st
from gee_utils import load_geojson, detect_columns, normalize_geojson


def _mapping_ui(raw, detected):
    """Show column mapping widgets, return col_map {old: new}."""
    cols = detected["all_cols"]
    col_map = {}

    st.markdown("**จับคู่ Column**")

    # ── FIELD_CODE ──
    default_fc = detected.get("FIELD_CODE") or cols[0]
    fc_idx = cols.index(default_fc) if default_fc in cols else 0
    sel_fc = st.selectbox("🔑 รหัสแปลง *", cols, index=fc_idx,
                          help="column ที่ใช้เป็น ID ของแต่ละแปลง")
    if sel_fc != "FIELD_CODE":
        col_map[sel_fc] = "FIELD_CODE"

    # ── AREA_RAI ──
    area_opts = ["(ไม่มี)"] + cols
    default_area = detected.get("AREA_RAI") or "(ไม่มี)"
    area_idx = area_opts.index(default_area) if default_area in area_opts else 0
    sel_area = st.selectbox("📐 พื้นที่ (ไร่)", area_opts, index=area_idx)
    if sel_area != "(ไม่มี)" and sel_area != "AREA_RAI":
        col_map[sel_area] = "AREA_RAI"

    # ── Planting Date columns ──
    if detected["PD_cols"]:
        st.caption(f"✅ พบวันปลูก {len(detected['PD_cols'])} ปี: {', '.join(detected['PD_cols'])}")
    else:
        st.markdown("**📅 วันปลูก** — ระบุทีละปี")

        if "pd_rows" not in st.session_state:
            st.session_state.pd_rows = [{"year": "65-66", "col": cols[0]}]

        to_delete = None
        for i, row in enumerate(st.session_state.pd_rows):
            c1, c2, c3 = st.columns([2, 3, 1])
            with c1:
                yr = st.text_input("ปี", row["year"], key=f"pd_yr_{i}",
                                   placeholder="เช่น 65-66")
            with c2:
                ci = cols.index(row["col"]) if row["col"] in cols else 0
                col_sel = st.selectbox("Column", cols, index=ci, key=f"pd_col_{i}")
            with c3:
                st.markdown("<div style='margin-top:28px'>", unsafe_allow_html=True)
                if st.button("✕", key=f"pd_del_{i}",
                             disabled=len(st.session_state.pd_rows) == 1):
                    to_delete = i
                st.markdown("</div>", unsafe_allow_html=True)
            st.session_state.pd_rows[i] = {"year": yr, "col": col_sel}
            if yr and col_sel:
                col_map[col_sel] = f"PD_{yr.replace('-', '_')}"

        if to_delete is not None:
            st.session_state.pd_rows.pop(to_delete)
            st.rerun()

        if st.button("+ เพิ่มปี", use_container_width=True):
            st.session_state.pd_rows.append({"year": "", "col": cols[0]})
            st.rerun()

    # ── Crop Type columns ──
    if detected["CT_cols"]:
        st.caption(f"✅ พบประเภทอ้อย: {', '.join(detected['CT_cols'])}")
    else:
        ct_opts = ["(ไม่มี)"] + cols
        sel_ct = st.selectbox("🌾 ประเภทอ้อย (CT_XX_XX)", ct_opts, index=0)
        if "pd_rows" in st.session_state and sel_ct != "(ไม่มี)":
            for row in st.session_state.pd_rows:
                yr = row.get("year", "")
                if yr:
                    col_map[sel_ct] = f"CT_{yr.replace('-', '_')}"
                    break

    return col_map


def render_upload_sidebar():
    """Render sidebar uploader + mapping. Returns normalized geojson_data."""
    with st.sidebar:
        st.markdown("### 📁 ข้อมูล GeoJSON")

        uploaded = st.file_uploader(
            "อัพโหลดไฟล์ใหม่",
            type=["geojson", "json"],
            help="ถ้าไม่อัพโหลด จะใช้ parcel4.geojson ตั้งต้น"
        )

        if uploaded is None:
            n = 297
            st.caption(f"📌 ใช้ข้อมูลตั้งต้น: parcel4.geojson ({n} แปลง)")
            # reset pd_rows ถ้าเคยตั้งไว้
            st.session_state.pop("pd_rows", None)
            return load_geojson()

        # ── โหลดไฟล์ ──
        try:
            raw = json.load(uploaded)
        except Exception:
            st.error("❌ อ่านไฟล์ไม่ได้ — กรุณาตรวจสอบรูปแบบ GeoJSON")
            return load_geojson()

        if "features" not in raw or not raw["features"]:
            st.error("❌ ไม่พบ features ในไฟล์")
            return load_geojson()

        n = len(raw["features"])
        detected = detect_columns(raw)
        cols = detected["all_cols"]

        st.success(f"✅ {n} แปลง · {len(cols)} columns")

        # ── ตรวจว่าเป็น standard format แล้วหรือยัง ──
        already_standard = (
            "FIELD_CODE" in cols and
            len(detected["PD_cols"]) > 0
        )
        if already_standard:
            st.caption("รูปแบบ column ถูกต้องแล้ว ไม่ต้อง mapping")
            return raw

        # ── แสดง mapping UI ──
        col_map = _mapping_ui(raw, detected)

        # ── Preview ──
        if col_map:
            with st.expander("🔍 ดู mapping"):
                for k, v in col_map.items():
                    st.caption(f"`{k}` → `{v}`")

        return normalize_geojson(raw, col_map)
