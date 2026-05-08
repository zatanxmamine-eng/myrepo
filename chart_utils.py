# chart_utils.py
import matplotlib as mlp
import matplotlib.font_manager
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import os
import urllib.request


def setup_thai_font():
    font_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thsarabunnew-webfont.ttf")
    if not os.path.exists(font_path):
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/Phonbopit/sarabun-webfont/master/fonts/thsarabunnew-webfont.ttf",
            font_path,
        )
    mlp.font_manager.fontManager.addfont(font_path)
    mlp.rc("font", family="TH Sarabun New", size=11)


setup_thai_font()


def chart_savi_bar(df):
    """Bar chart SAVI_mean per parcel colored by STATUS"""
    fig = px.bar(
        df.dropna(subset=["SAVI_mean"]),
        x="FIELD_CODE", y="SAVI_mean", color="STATUS",
        color_discrete_map={
            "🟢 งอกดี": "#00aa00", "🟡 ปานกลาง": "#ffdd00",
            "🟠 น้อย": "#ff6600", "🔴 ไม่งอก": "#dd0000",
        },
        title="SAVI Mean รายแปลง",
        labels={"SAVI_mean": "SAVI", "FIELD_CODE": "รหัสแปลง"},
    )
    fig.add_hline(y=0.35, line_dash="dash", line_color="lightgreen", annotation_text="เกณฑ์งอกดี")
    return fig


def chart_ay_scatter(df, geojson_data, year):
    """Scatter SAVI_mean vs actual yield (AY)"""
    ay_col = f"AY_{year.replace('-', '_')}"
    props = {
        f["properties"]["FIELD_CODE"]: f["properties"].get(ay_col)
        for f in geojson_data["features"]
    }
    df2 = df.copy()
    df2["AY"] = df2["FIELD_CODE"].map(props)
    df2 = df2.dropna(subset=["SAVI_mean", "AY"])
    fig = px.scatter(
        df2, x="SAVI_mean", y="AY", text="FIELD_CODE", color="STATUS",
        title=f"SAVI vs ผลผลิตจริง ({year})",
        labels={"SAVI_mean": "SAVI Mean", "AY": "ผลผลิต (ตัน/ไร่)"},
    )
    fig.update_traces(textposition="top center")
    return fig


def chart_crop_boxplot(df):
    """Box plot SAVI_mean by crop type"""
    df2 = df.dropna(subset=["SAVI_mean", "CROP_TYPE"])
    fig = px.box(
        df2, x="CROP_TYPE", y="SAVI_mean", color="CROP_TYPE",
        title="SAVI Mean แยกตามประเภทอ้อย",
        labels={"CROP_TYPE": "ประเภทอ้อย", "SAVI_mean": "SAVI Mean"},
    )
    return fig


def chart_chirps(chirps_weekly):
    """Bar chart of weekly CHIRPS rainfall"""
    df = pd.DataFrame(chirps_weekly)
    fig = go.Figure()
    fig.add_bar(x=df["Week"], y=df["CHIRPS_mm"], name="ฝน (mm)", marker_color="#e05c00", opacity=0.6)
    fig.update_layout(
        title="ปริมาณฝน CHIRPS รายสัปดาห์",
        xaxis_title="สัปดาห์",
        yaxis_title="ฝน (mm)",
    )
    return fig


def chart_year_compare(year_compare_dict, field_code):
    """Bar chart comparing SAVI across years for one parcel"""
    years = list(year_compare_dict.keys())
    values = [year_compare_dict[y] or 0 for y in years]
    fig = px.bar(
        x=years, y=values,
        title=f"เปรียบ SAVI ข้ามปี — แปลง {field_code}",
        labels={"x": "ปีการผลิต", "y": "SAVI Mean"},
        color=values, color_continuous_scale="Greens",
    )
    fig.add_hline(y=0.35, line_dash="dash", line_color="lightgreen", annotation_text="เกณฑ์งอกดี")
    return fig
