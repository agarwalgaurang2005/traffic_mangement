from flask import Flask, render_template, request, jsonify
import requests
import os

app = Flask(__name__)

MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "pk.eyJ1IjoiYWdhcndhbGdhdXJhbmciLCJhIjoiY21lbDM0c2hxMDczdDJqczU0djJ0ZW81aSJ9.P6BVtjJ4lfXFnBxZ7vV2DQ")
REQUEST_TIMEOUT = 12  # seconds
REFRESH_SECONDS = 30  # frontend polling interval

def geocode_place(place):
    """Return (lat, lon) for a place using Mapbox Geocoding (restricted to India)."""
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{place}.json"
    params = {
        "access_token": MAPBOX_TOKEN,
        "limit": 1,
        "country": "IN"
    }
    r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("features"):
        lon, lat = data["features"][0]["geometry"]["coordinates"]
        return lat, lon
    return None, None

def mapbox_directions(lat1, lon1, lat2, lon2, profile="driving", annotations=None, alternatives=False):
    """Call Mapbox Directions API. Returns raw JSON."""
    base = f"https://api.mapbox.com/directions/v5/mapbox/{profile}/{lon1},{lat1};{lon2},{lat2}"
    params = {
        "access_token": MAPBOX_TOKEN,
        "geometries": "geojson",
        "overview": "full",
        "": "false",
        "alternatives": str(alternatives).lower(),
    }
    if annotations:
        params["annotations"] = annotations
    r = requests.get(base, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()

def color_for_congestion(c):
    """Mapbox congestion strings -> colors."""
    return {
        "low": "green",
        "moderate": "orange",
        "heavy": "red",
        "severe": "darkred",
        "unknown": "gray",
        None: "gray"
    }.get(c, "gray")

# ----------------- ROUTES -----------------
@app.route("/", methods=["GET"])
def home():
    return render_template("map_live.html", MAPBOX_TOKEN=MAPBOX_TOKEN, REFRESH_SECONDS=REFRESH_SECONDS)

@app.route("/api/route", methods=["GET"])
def api_route():
    """Returns multiple alternative routes with congestion details."""
    start = request.args.get("start", "").strip()
    end = request.args.get("end", "").strip()
    if not start or not end:
        return jsonify({"error": "start and end are required"}), 400

    # 1) Geocode (restricted to India)
    lat1, lon1 = geocode_place(start)
    lat2, lon2 = geocode_place(end)
    print("Geocoded start:", start, lat1, lon1)  # ✅ Debugging
    print("Geocoded end:", end, lat2, lon2)
    if lat1 is None or lat2 is None:
        return jsonify({"error": "Could not geocode one or both places."}), 400

    # 2) Base routes (no traffic)
    base_json = mapbox_directions(lat1, lon1, lat2, lon2, profile="driving", alternatives=True)
    base_routes = base_json.get("routes", [])
    if not base_routes:
        return jsonify({"error": "No base routes found"}), 404

    # 3) Live traffic routes (with annotations)
    ann = "congestion,congestion_numeric,speed,duration,distance"
    live_json = mapbox_directions(lat1, lon1, lat2, lon2, profile="driving-traffic", annotations=ann, alternatives=True)
    live_routes = live_json.get("routes", [])
    if not live_routes:
        return jsonify({"error": "No live traffic routes found"}), 404

    routes_payload = []
    for ridx, live_route in enumerate(live_routes):
        distance_m = live_route.get("distance", 0)
        live_duration = live_route.get("duration", 0)
        base_duration = base_routes[ridx]["duration"] if ridx < len(base_routes) else live_duration

        leg = (live_route.get("legs") or [{}])[0]
        ann = leg.get("annotation", {})

        congestions = ann.get("congestion", []) or []
        speeds = ann.get("speed", []) or []
        seg_durations = ann.get("duration", []) or []
        coords = live_route.get("geometry", {}).get("coordinates", [])

        segments = []
        for i in range(len(coords) - 1):
            lon_a, lat_a = coords[i]
            lon_b, lat_b = coords[i + 1]
            cong = congestions[i] if i < len(congestions) else None
            speed_ms = speeds[i] if i < len(speeds) else None
            dur_s = seg_durations[i] if i < len(seg_durations) else None

            segments.append({
                "coords": [[lat_a, lon_a], [lat_b, lon_b]],
                "congestion": cong,
                "color": color_for_congestion(cong),
                "speed_kmh": round(speed_ms * 3.6, 1) if isinstance(speed_ms, (int, float)) else None,
                "duration_s": dur_s
            })

        delay_s = max(0, round(live_duration - base_duration))

        routes_payload.append({
            "id": ridx,
            "distance_m": distance_m,
            "durations": {
                "base_s": round(base_duration),
                "traffic_s": round(live_duration),
                "delay_s": delay_s
            },
            "segments": segments
        })

    return jsonify({
        "start": {"name": start, "lat": lat1, "lon": lon1},
        "end": {"name": end, "lat": lat2, "lon": lon2},
        "routes": routes_payload
    })

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=True, use_reloader=False)

