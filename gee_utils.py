# gee_utils.py
import ee
import json
import os
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

GEOJSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parcel4.geojson")

@st.cache_data
def load_geojson():
    with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def init_gee(project="sugarcane-495504"):
    try:
        # Streamlit Cloud: write credentials from secrets
        if "earthengine" in st.secrets:
            creds_dir = os.path.expanduser("~/.config/earthengine")
            os.makedirs(creds_dir, exist_ok=True)
            with open(os.path.join(creds_dir, "credentials"), "w") as f:
                json.dump(dict(st.secrets["earthengine"]), f)
        ee.Initialize(project=project)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=project)

def get_years(geojson_data):
    """ดึงรายการปีที่มีข้อมูลจาก field PD_XX_XX"""
    years = set()
    for f in geojson_data["features"]:
        for key, val in f["properties"].items():
            if key.startswith("PD_") and val:
                years.add(key.replace("PD_", "").replace("_", "-"))
    return sorted(years)

def get_crop_types(geojson_data, year):
    col = f"CT_{year.replace('-', '_')}"
    types = set()
    for f in geojson_data["features"]:
        v = f["properties"].get(col)
        if v:
            types.add(v)
    return ["ทั้งหมด"] + sorted(types)

def get_varieties(geojson_data, year):
    yr = year.split("-")[0]
    col = f"Variety_{yr}"
    varieties = set()
    for f in geojson_data["features"]:
        v = f["properties"].get(col)
        if v:
            varieties.add(v)
    return ["ทั้งหมด"] + sorted(varieties)

def filter_features(geojson_data, year, crop_type, variety, area_min, area_max, search):
    ct_col = f"CT_{year.replace('-', '_')}"
    yr = year.split("-")[0]
    var_col = f"Variety_{yr}"
    results = []
    for f in geojson_data["features"]:
        p = f["properties"]
        if crop_type != "ทั้งหมด" and p.get(ct_col) != crop_type:
            continue
        if variety != "ทั้งหมด" and p.get(var_col) != variety:
            continue
        area = p.get("AREA_RAI", 0) or 0
        if not (area_min <= area <= area_max):
            continue
        if search and search.upper() not in p.get("FIELD_CODE", "").upper():
            continue
        results.append(f)
    return results


def calc_indices(image):
    savi = image.expression(
        "((NIR - RED) / (NIR + RED + 0.5)) * 1.5",
        {"NIR": image.select("B8"), "RED": image.select("B4")}
    ).rename("SAVI")
    ndwi = image.normalizedDifference(["B3", "B8"]).rename("NDWI")
    ndre = image.normalizedDifference(["B8", "B5"]).rename("NDRE")
    return image.addBands([savi, ndwi, ndre])


def get_s2(parcel_ee, start_str, days=90, cloud_pct=30):
    start = datetime.strptime(start_str, "%Y-%m-%d")
    end = start + timedelta(days=days)
    return (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(parcel_ee)
        .filterDate(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_pct))
        .map(calc_indices)
    )


def run_savi_ndwi(sugarcane_fc, field_code, start_str):
    """Return dict of SAVI/NDWI/NDRE stats for one parcel"""
    parcel = sugarcane_fc.filter(ee.Filter.eq("FIELD_CODE", field_code))
    s2 = get_s2(parcel, start_str)
    img_count = s2.size().getInfo()
    if img_count == 0:
        return {"img_count": 0, "STATUS": "ไม่มีภาพดาวเทียม"}

    median = s2.median().clip(parcel)
    geom = parcel.geometry()

    stats_img = ee.Image.cat([
        median.select("SAVI").gte(0.35).rename("Good_Pct"),
        median.select("SAVI").lt(0.25).rename("Poor_Pct"),
        median.select("NDWI").lt(-0.1).rename("Dry_Pct"),
    ]).addBands(median.select(["SAVI", "NDWI", "NDRE"]))

    stats = stats_img.reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=geom, scale=10, maxPixels=1e9
    ).getInfo()

    savi_mean = stats.get("SAVI_mean") or 0
    good_pct = (stats.get("Good_Pct_mean") or 0) * 100
    poor_pct = (stats.get("Poor_Pct_mean") or 0) * 100
    dry_pct = (stats.get("Dry_Pct_mean") or 0) * 100

    if good_pct >= 70:     status = "🟢 งอกดี"
    elif good_pct >= 40:   status = "🟡 ปานกลาง"
    elif poor_pct >= 50:   status = "🔴 ไม่งอก"
    else:                  status = "🟠 น้อย"

    return {
        "img_count":  img_count,
        "SAVI_mean":  round(savi_mean, 4),
        "SAVI_sd":    round(stats.get("SAVI_stdDev") or 0, 4),
        "NDWI_mean":  round(stats.get("NDWI_mean") or 0, 4),
        "NDRE_mean":  round(stats.get("NDRE_mean") or 0, 4),
        "Good_pct":   round(good_pct, 1),
        "Poor_pct":   round(poor_pct, 1),
        "Dry_pct":    round(dry_pct, 1),
        "STATUS":     status,
    }


def run_growth_speed(sugarcane_fc, field_code, start_str):
    parcel = sugarcane_fc.filter(ee.Filter.eq("FIELD_CODE", field_code))
    s2 = get_s2(parcel, start_str)
    if s2.size().getInfo() == 0:
        return {"GrowthSpeed": None}

    def add_time(img):
        d = ee.Date(img.get("system:time_start")).difference(ee.Date(start_str), "day")
        return img.addBands(ee.Image.constant(d).rename("Time").float())

    speed = (
        s2.map(add_time).select(["Time", "SAVI"])
        .reduce(ee.Reducer.linearFit()).select("scale")
        .reduceRegion(ee.Reducer.mean(), parcel.geometry(), scale=10, maxPixels=1e9)
        .getInfo().get("scale", 0)
    )
    return {"GrowthSpeed": round(speed, 6) if speed else None}


def run_delta_ndvi(sugarcane_fc, field_code, start_str):
    parcel = sugarcane_fc.filter(ee.Filter.eq("FIELD_CODE", field_code))
    start = datetime.strptime(start_str, "%Y-%m-%d")
    mid1 = start + timedelta(days=30)
    mid2 = start + timedelta(days=60)
    end  = start + timedelta(days=90)

    def get_ndvi(d1, d2):
        return (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(parcel)
            .filterDate(d1.strftime("%Y-%m-%d"), d2.strftime("%Y-%m-%d"))
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40))
            .map(lambda img: img.normalizedDifference(["B8", "B4"]).rename("NDVI"))
            .median().clip(parcel)
        )

    def mean_val(img):
        return img.reduceRegion(ee.Reducer.mean(), parcel.geometry(), 10, maxPixels=1e9).getInfo().get("NDVI")

    p1, p2, p3 = get_ndvi(start, mid1), get_ndvi(mid1, mid2), get_ndvi(mid2, end)
    v1, v2, v3 = mean_val(p1), mean_val(p2), mean_val(p3)

    d12 = round(v2 - v1, 4) if v1 and v2 else None
    d23 = round(v3 - v2, 4) if v2 and v3 else None
    d13 = round(v3 - v1, 4) if v1 and v3 else None
    return {"Delta_12": d12, "Delta_23": d23, "Delta_13": d13}


def run_chirps(sugarcane_fc, field_code, start_str):
    parcel = sugarcane_fc.filter(ee.Filter.eq("FIELD_CODE", field_code))
    start = datetime.strptime(start_str, "%Y-%m-%d")
    weeks = [(w+1, start + timedelta(days=w*7), start + timedelta(days=(w+1)*7)) for w in range(12)]
    records = []
    for wk, ws, we in weeks:
        rain = (
            ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
            .filterDate(ws.strftime("%Y-%m-%d"), we.strftime("%Y-%m-%d"))
            .filterBounds(parcel)
            .select("precipitation").sum()
            .reduceRegion(ee.Reducer.mean(), parcel.geometry().buffer(5000), 5566, maxPixels=1e9)
            .getInfo().get("precipitation")
        )
        records.append({"Week": f"W{wk:02d}", "CHIRPS_mm": round(rain, 2) if rain else None})
    return {"chirps_weekly": records}


def run_all(geojson_data, field_code, year, analyses):
    """Run selected analyses for one parcel, return combined dict"""
    sugarcane_fc = ee.FeatureCollection(geojson_data)
    pd_col = f"PD_{year.replace('-', '_')}"
    ct_col = f"CT_{year.replace('-', '_')}"
    props_map = {f["properties"]["FIELD_CODE"]: f["properties"] for f in geojson_data["features"]}
    p = props_map.get(field_code, {})
    start_str = p.get(pd_col)

    result = {
        "FIELD_CODE": field_code,
        "AREA_RAI":   p.get("AREA_RAI"),
        "CROP_TYPE":  p.get(ct_col),
        "START_DATE": start_str,
        "YEAR":       year,
    }

    if not start_str:
        result["STATUS"] = "ไม่มีวันปลูก"
        return result

    if "savi" in analyses or "ndre" in analyses:
        result.update(run_savi_ndwi(sugarcane_fc, field_code, start_str))
    if "growth" in analyses:
        result.update(run_growth_speed(sugarcane_fc, field_code, start_str))
    if "delta_ndvi" in analyses:
        result.update(run_delta_ndvi(sugarcane_fc, field_code, start_str))
    if "chirps" in analyses:
        result.update(run_chirps(sugarcane_fc, field_code, start_str))

    return result


def export_geotiff(geojson_data, field_code, year, image_type="classification"):
    """Submit GEE Export task to Google Drive"""
    sugarcane_fc = ee.FeatureCollection(geojson_data)
    parcel = sugarcane_fc.filter(ee.Filter.eq("FIELD_CODE", field_code))
    pd_col = f"PD_{year.replace('-', '_')}"
    props_map = {f["properties"]["FIELD_CODE"]: f["properties"] for f in geojson_data["features"]}
    start_str = props_map.get(field_code, {}).get(pd_col)
    if not start_str:
        return None

    s2 = get_s2(parcel, start_str)
    if s2.size().getInfo() == 0:
        return None

    median = s2.median().clip(parcel)
    savi = median.select("SAVI")
    classified = (
        savi.where(savi.lt(0.10), 0)
            .where(savi.gte(0.10).And(savi.lt(0.25)), 1)
            .where(savi.gte(0.25).And(savi.lt(0.35)), 2)
            .where(savi.gte(0.35), 3)
            .rename("GerminationClass").toInt()
    )

    task = ee.batch.Export.image.toDrive(
        image=classified,
        description=f"Class_{field_code}_{year.replace('-', '_')}",
        fileNamePrefix=f"class_{field_code}",
        region=parcel.geometry().bounds(),
        scale=10,
        crs="EPSG:32648",
        maxPixels=1e9,
        fileFormat="GeoTIFF",
        folder="GEE_SugarcaneExports",
    )
    task.start()
    return task


def run_year_compare(geojson_data, field_code, years=None):
    """Compare SAVI across years for one parcel"""
    if years is None:
        years = ["65-66", "66-67", "67-68"]
    sugarcane_fc = ee.FeatureCollection(geojson_data)
    props_map = {f["properties"]["FIELD_CODE"]: f["properties"] for f in geojson_data["features"]}
    p = props_map.get(field_code, {})
    results = {}
    for yr in years:
        pd_col = f"PD_{yr.replace('-', '_')}"
        start_str = p.get(pd_col)
        if not start_str:
            results[yr] = None
            continue
        r = run_savi_ndwi(sugarcane_fc, field_code, start_str)
        results[yr] = r.get("SAVI_mean")
    return {"year_compare": results}
