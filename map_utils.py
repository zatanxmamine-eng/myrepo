# map_utils.py
import folium
import json
from shapely.geometry import shape, Point

def make_parcel_map(geojson_data, filtered_codes, selected_codes, center=None):
    """
    geojson_data: dict full geojson
    filtered_codes: set of FIELD_CODE that passed filter
    selected_codes: set/list of FIELD_CODE already selected
    """
    if center is None:
        first_geom = shape(geojson_data["features"][0]["geometry"])
        c = first_geom.centroid
        center = [c.y, c.x]

    m = folium.Map(location=center, zoom_start=13, tiles="CartoDB dark_matter")

    for f in geojson_data["features"]:
        code = f["properties"].get("FIELD_CODE", "")
        area = f["properties"].get("AREA_RAI", 0)
        is_selected = code in selected_codes
        is_filtered = code in filtered_codes

        if is_selected:
            color, fill_color, opacity = "#00ff88", "#00ff88", 0.5
        elif is_filtered:
            color, fill_color, opacity = "#60a5fa", "#60a5fa", 0.2
        else:
            color, fill_color, opacity = "#374151", "#374151", 0.1

        folium.GeoJson(
            f,
            style_function=lambda x, c=color, fc=fill_color, op=opacity: {
                "color": c, "weight": 1.5,
                "fillColor": fc, "fillOpacity": op,
            },
            tooltip=f"{code} ({area} ไร่)",
        ).add_to(m)

    return m

def find_clicked_parcel(geojson_data, lat, lon):
    """Find which parcel contains the clicked lat/lon"""
    pt = Point(lon, lat)
    for f in geojson_data["features"]:
        if shape(f["geometry"]).contains(pt):
            return f["properties"].get("FIELD_CODE")
    return None
