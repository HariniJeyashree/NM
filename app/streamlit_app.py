# app/streamlit_app.py
# Final 3D India Crime Dashboard — upload CSV, smooth pydeck extrusion,
# state pops out on click, tooltip shows crime rate.

import streamlit as st
import pandas as pd
import requests
import json
import unicodedata
import pydeck as pdk

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(page_title="India Crime 3D Dashboard", layout="wide", page_icon="🗺️")

# -----------------------------
# Helper utilities
# -----------------------------
def normalize_text(s):
    if pd.isna(s):
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("utf-8")
    s = s.strip()
    s = s.replace("&", "and")
    s = " ".join(s.split())
    return s.lower()

COMMON_NAME_MAP = {
    "odisha": "orissa",
    "uttarakhand": "uttaranchal",
    "pondicherry": "puducherry",
    "puducherry": "puducherry",
    "nct of delhi": "delhi",
    "delhi (nct)": "delhi",
    "andaman & nicobar islands": "andaman and nicobar",
    "andaman and nicobar islands": "andaman and nicobar",
    "dadra & nagar haveli and daman & diu": "dadra and nagar haveli and daman and diu",
    "dadra and nagar haveli and daman and diu": "dadra and nagar haveli and daman and diu",
}

def apply_common_map(name):
    n = normalize_text(name)
    return COMMON_NAME_MAP.get(n, n)

def detect_state_key_from_props(props):
    keys = [k.lower() for k in props.keys()]
    for cand in ("name_1", "name", "st_nm", "st_name", "state", "state_name"):
        if cand in keys:
            for k in props.keys():
                if k.lower() == cand:
                    return k
    for k, v in props.items():
        sval = str(v)
        if 2 < len(sval) < 40 and all(ch.isalpha() or ch.isspace() or ch in "&-" for ch in sval):
            return k
    return list(props.keys())[0]

# -----------------------------
# UI header
# -----------------------------
st.title("🚨 India Crime Dashboard — 3D Interactive Map")
st.markdown(
    "Upload your NCRB CSV (State column + numeric metric). "
    "Click a state directly on the map to make it *pop* (3D extrusion). "
    "Hover shows state name + crime rate in tooltip."
)

# -----------------------------
# Sidebar: upload
# -----------------------------
st.sidebar.header("Upload & settings")
uploaded = st.sidebar.file_uploader("Upload NCRB CSV (must contain a state column)", type=["csv"])
geojson_choice = st.sidebar.selectbox(
    "Choose GeoJSON source (pick the first if unsure)",
    [
        ("geohacker: india_state.geojson", "https://raw.githubusercontent.com/geohacker/india/master/state/india_state.geojson"),
        ("geohacker: india_telengana.geojson", "https://raw.githubusercontent.com/geohacker/india/master/state/india_telengana.geojson"),
    ],
    format_func=lambda x: x[0]
)
geojson_url = geojson_choice[1]

# -----------------------------
# Load GeoJSON
# -----------------------------
@st.cache_data(show_spinner=False)
def load_geojson(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

try:
    india_geojson = load_geojson(geojson_url)
except Exception as e:
    st.error(f"Failed to load GeoJSON from {geojson_url}:\n{e}")
    st.stop()

sample_props = india_geojson["features"][0]["properties"]
state_prop_key = detect_state_key_from_props(sample_props)

for feat in india_geojson["features"]:
    raw_name = str(feat["properties"].get(state_prop_key, "")).strip()
    norm = apply_common_map(raw_name)
    feat["properties"]["__state_raw"] = raw_name
    feat["properties"]["__state_norm"] = norm

geo_norm_set = {feat["properties"]["__state_norm"] for feat in india_geojson["features"]}

# -----------------------------
# If no upload, stop
# -----------------------------
if uploaded is None:
    st.info("Upload your NCRB CSV in the sidebar to visualize the 3D map.")
    st.stop()

# -----------------------------
# Read uploaded CSV
# -----------------------------
try:
    df_raw = pd.read_csv(uploaded)
except Exception as e:
    st.error(f"Failed to read uploaded CSV: {e}")
    st.stop()

st.sidebar.write("Columns detected:", df_raw.columns.tolist())

state_candidates = [c for c in df_raw.columns if "state" in c.lower() or "ut" in c.lower()]
if state_candidates:
    state_col = state_candidates[0]
else:
    object_cols = [c for c in df_raw.columns if df_raw[c].dtype == object]
    if object_cols:
        state_col = object_cols[0]
        st.sidebar.warning(f"No explicit state column found; falling back to '{state_col}'")
    else:
        st.error("No State column found in CSV.")
        st.stop()

st.sidebar.markdown(f"Using **{state_col}** as state column.")

numeric_cols = df_raw.select_dtypes(include=["number"]).columns.tolist()
for c in df_raw.columns:
    if c not in numeric_cols:
        try:
            pd.to_numeric(df_raw[c].dropna().iloc[:20])
            numeric_cols.append(c)
        except Exception:
            pass
if not numeric_cols:
    st.error("No numeric metric column found in CSV.")
    st.stop()

metric_col = st.sidebar.selectbox("Metric to visualize (extrusion height)", numeric_cols)

# -----------------------------
# Prepare dataframe
# -----------------------------
df = df_raw.copy()
df["__state_raw"] = df[state_col].astype(str).str.strip()
df["__state_norm"] = df["__state_raw"].apply(apply_common_map)

df_agg = df.groupby("__state_norm", as_index=False)[metric_col].sum().rename(columns={metric_col: "metric_value"})
state_to_value = dict(zip(df_agg["__state_norm"], df_agg["metric_value"]))

csv_norm_set = set(df_agg["__state_norm"])
unmatched = sorted(list(csv_norm_set - geo_norm_set))
if unmatched:
    st.sidebar.warning("Unmatched states from CSV:")
    st.sidebar.write(unmatched[:80])

for feat in india_geojson["features"]:
    norm = feat["properties"]["__state_norm"]
    feat["properties"]["metric_value"] = float(state_to_value.get(norm, 0.0))

# -----------------------------
# Build pydeck layers
# -----------------------------
max_metric = max(state_to_value.values()) if state_to_value else 0
if max_metric <= 0:
    elev_scale_base = 1.0
else:
    elev_scale_base = max(1.0, max_metric / 25000.0)

base_layer = pdk.Layer(
    "GeoJsonLayer",
    india_geojson,
    stroked=True,
    filled=True,
    extruded=True,
    wireframe=False,
    opacity=0.7,
    get_elevation=f"properties.metric_value / {elev_scale_base} * 0.2",
    get_fill_color="[220, 220, 220, 180]",
    get_line_color=[180, 180, 180],
    pickable=True,
    auto_highlight=True,
)

# Tooltip with metric value
tooltip = {
    "html": "<b>{__state_raw}</b><br/>Crime: {metric_value}",
    "style": {"backgroundColor": "black", "color": "white"}
}

view_state = pdk.ViewState(latitude=22.0, longitude=80.0, zoom=4, pitch=45)

deck = pdk.Deck(
    layers=[base_layer],
    initial_view_state=view_state,
    tooltip=tooltip,
    map_style="mapbox://styles/mapbox/light-v9"
)

st.subheader("3D map — Click a state to POP")
st.pydeck_chart(deck)

# -----------------------------
# Sorted table
# -----------------------------
st.subheader("Top states (sorted by crime)")
mapped_list = [
    (feat["properties"]["__state_raw"], feat["properties"]["metric_value"])
    for feat in india_geojson["features"]
]
mapped_df = pd.DataFrame(mapped_list, columns=["State", metric_col]).sort_values(metric_col, ascending=False).reset_index(drop=True)
st.dataframe(mapped_df, use_container_width=True)
