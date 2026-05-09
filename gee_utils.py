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


def detect_columns(geojson_data):
    """Auto-detect standard column roles from GeoJSON properties."""
    if not geojson_data.get("features"):
        return {}
    cols = list(geojson_data["features"][0]["properties"].keys())
    low  = {c.lower(): c for c in cols}

    def find(keywords):
        for kw in keywords:
            for lc, orig in low.items():
                if kw in lc:
                    return orig
        return None

    return {
        "all_cols":     cols,
        "FIELD_CODE":   find(["field_code", "fieldcode", "field_id", "parcel_id", "plot_id"]),
        "AREA_RAI":     find(["area_rai", "area", "rai", "size"]),
        "PD_cols":      [c for c in cols if c.startswith("PD_")],
        "CT_cols":      [c for c in cols if c.startswith("CT_")],
        "Variety_cols": [c for c in cols if c.startswith("Variety_")],
    }


def normalize_geojson(geojson_data, col_map):
    """Rename properties in all features per col_map {old_name: new_name}."""
    if not col_map:
        return geojson_data
    import copy
    result = copy.deepcopy(geojson_data)
    for f in result["features"]:
        props = f["properties"]
        for old, new in col_map.items():
            if old in props and old != new:
                props[new] = props.pop(old)
    return result

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


_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d", "%d-%m-%Y"]

def parse_date(value):
    """Try multiple date formats, return datetime or None"""
    if not value or str(value).strip().lower() in ("", "none", "n/a", "na", "0", "-"):
        return None
    s = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def get_s2(parcel_ee, start_str, days=90, cloud_pct=30):
    start = parse_date(start_str)
    if start is None:
        raise ValueError(f"parse_date ไม่รู้จักรูปแบบวันที่: {start_str!r}")
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
    raw_date = p.get(pd_col)
    parsed   = parse_date(raw_date)
    start_str = parsed.strftime("%Y-%m-%d") if parsed else None

    result = {
        "FIELD_CODE": field_code,
        "AREA_RAI":   p.get("AREA_RAI"),
        "CROP_TYPE":  p.get(ct_col),
        "START_DATE": start_str or raw_date,
        "YEAR":       year,
    }

    if start_str is None:
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


def run_batch_all(geojson_data, field_codes, year, analyses):
    """Batch GEE — groups parcels by planting date, one reduceRegions call per group."""
    from collections import defaultdict

    pd_col      = f"PD_{year.replace('-', '_')}"
    ct_col      = f"CT_{year.replace('-', '_')}"
    props_map   = {f["properties"]["FIELD_CODE"]: f["properties"] for f in geojson_data["features"]}
    feat_lookup = {f["properties"]["FIELD_CODE"]: f for f in geojson_data["features"]}

    date_groups = defaultdict(list)
    results = {}

    for fc in field_codes:
        p       = props_map.get(fc, {})
        raw_date = p.get(pd_col)
        parsed  = parse_date(raw_date)
        base = {
            "FIELD_CODE": fc,
            "AREA_RAI":   p.get("AREA_RAI"),
            "CROP_TYPE":  p.get(ct_col),
            "START_DATE": parsed.strftime("%Y-%m-%d") if parsed else raw_date,
            "YEAR":       year,
        }
        results[fc] = base
        if parsed is None:
            base["STATUS"] = "ไม่มีวันปลูก"
        else:
            date_groups[parsed.strftime("%Y-%m-%d")].append(fc)

    for start_str, codes in date_groups.items():
        features = [feat_lookup[c] for c in codes if c in feat_lookup]
        sub_fc   = ee.FeatureCollection(features)

        # Fetch S2 once per date group if any band analysis needed
        s2, img_count = None, 0
        if any(a in analyses for a in ["savi", "ndre", "growth"]):
            s2        = get_s2(sub_fc, start_str)
            img_count = s2.size().getInfo()

        # ── SAVI / NDWI / NDRE ──
        if "savi" in analyses or "ndre" in analyses:
            if img_count == 0:
                for c in codes:
                    results[c].update({"img_count": 0, "STATUS": "ไม่มีภาพดาวเทียม"})
            else:
                median    = s2.median()
                stats_img = ee.Image.cat([
                    median.select("SAVI").gte(0.35).rename("Good_Pct"),
                    median.select("SAVI").lt(0.25).rename("Poor_Pct"),
                    median.select("NDWI").lt(-0.1).rename("Dry_Pct"),
                    median.select(["SAVI", "NDWI", "NDRE"]),
                ])
                reduced = stats_img.reduceRegions(
                    collection=sub_fc,
                    reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
                    scale=10,
                ).getInfo()
                for feat in reduced["features"]:
                    rp  = feat["properties"]
                    fc  = rp.get("FIELD_CODE")
                    if fc not in results:
                        continue
                    savi_mean = rp.get("SAVI_mean") or 0
                    good_pct  = (rp.get("Good_Pct_mean") or 0) * 100
                    poor_pct  = (rp.get("Poor_Pct_mean") or 0) * 100
                    dry_pct   = (rp.get("Dry_Pct_mean") or 0) * 100
                    if good_pct >= 70:   status = "🟢 งอกดี"
                    elif good_pct >= 40: status = "🟡 ปานกลาง"
                    elif poor_pct >= 50: status = "🔴 ไม่งอก"
                    else:                status = "🟠 น้อย"
                    results[fc].update({
                        "img_count": img_count,
                        "SAVI_mean": round(savi_mean, 4),
                        "SAVI_sd":   round(rp.get("SAVI_stdDev") or 0, 4),
                        "NDWI_mean": round(rp.get("NDWI_mean") or 0, 4),
                        "NDRE_mean": round(rp.get("NDRE_mean") or 0, 4),
                        "Good_pct":  round(good_pct, 1),
                        "Poor_pct":  round(poor_pct, 1),
                        "Dry_pct":   round(dry_pct, 1),
                        "STATUS":    status,
                    })

        # ── Growth Speed ──
        if "growth" in analyses and img_count > 0:
            _start = start_str  # capture for closure

            def add_time(img):
                d = ee.Date(img.get("system:time_start")).difference(ee.Date(_start), "day")
                return img.addBands(ee.Image.constant(d).rename("Time").float())

            growth_img = (
                s2.map(add_time).select(["Time", "SAVI"])
                .reduce(ee.Reducer.linearFit()).select("scale")
            )
            growth_reduced = growth_img.reduceRegions(
                collection=sub_fc,
                reducer=ee.Reducer.mean(),
                scale=10,
            ).getInfo()
            for feat in growth_reduced["features"]:
                rp = feat["properties"]
                fc = rp.get("FIELD_CODE")
                if fc in results:
                    speed = rp.get("mean")
                    results[fc]["GrowthSpeed"] = round(speed, 6) if speed else None

        # ── Delta NDVI (3 time windows — keep per-parcel) ──
        if "delta_ndvi" in analyses:
            for c in codes:
                results[c].update(run_delta_ndvi(sub_fc, c, start_str))

        # ── CHIRPS (12 weeks, reduceRegions across all parcels per week) ──
        if "chirps" in analyses:
            start_dt   = datetime.strptime(start_str, "%Y-%m-%d")
            weeks      = [(w+1, start_dt + timedelta(days=w*7),
                           start_dt + timedelta(days=(w+1)*7)) for w in range(12)]
            chirps_data = {c: [] for c in codes}
            for wk, ws, we in weeks:
                rain_img = (
                    ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
                    .filterDate(ws.strftime("%Y-%m-%d"), we.strftime("%Y-%m-%d"))
                    .filterBounds(sub_fc)
                    .select("precipitation").sum()
                )
                rain_reduced = rain_img.reduceRegions(
                    collection=sub_fc,
                    reducer=ee.Reducer.mean(),
                    scale=5566,
                ).getInfo()
                for feat in rain_reduced["features"]:
                    rp = feat["properties"]
                    fc = rp.get("FIELD_CODE")
                    if fc in chirps_data:
                        rain = rp.get("mean")
                        chirps_data[fc].append({"Week": f"W{wk:02d}", "CHIRPS_mm": round(rain, 2) if rain else None})
            for c in codes:
                results[c]["chirps_weekly"] = chirps_data[c]

    return results


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
