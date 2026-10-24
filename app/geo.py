"""Small geodesy helpers (spherical earth is plenty for a window view)."""
import math

R_KM = 6371.0088
POINTS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
          "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def elevation_deg(alt_m, dist_km, home_elev_m=0.0):
    """Angle above the horizon from the observer, with earth-curvature drop."""
    d = max(dist_km * 1000.0, 1.0)
    dh = alt_m - home_elev_m - (d * d) / (2 * R_KM * 1000.0)
    return math.degrees(math.atan2(dh, d))


def compass(bearing):
    return POINTS[int((bearing % 360) / 22.5 + 0.5) % 16]


def offset_point(lat, lon, bearing, dist_km):
    """Point `dist_km` away from (lat, lon) along `bearing`."""
    b = math.radians(bearing)
    d = dist_km / R_KM
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180
