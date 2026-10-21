"""Small, bounded coordinate variations for stationary location simulation."""
import math
import random

EARTH_RADIUS_M = 6_371_000


class DriftPath:
    def __init__(self, latitude, longitude, radius_m, rng=None):
        self.latitude = math.radians(latitude)
        self.longitude = math.radians(longitude)
        self.radius_m = radius_m
        self.rng = rng or random.Random()
        self.x = self.y = 0.0
        self.goal_x = self.goal_y = 0.0

    def step(self):
        if math.hypot(self.goal_x - self.x, self.goal_y - self.y) < 0.35:
            angle = self.rng.uniform(0, math.tau)
            distance = self.radius_m * math.sqrt(self.rng.random())
            self.goal_x, self.goal_y = distance * math.cos(angle), distance * math.sin(angle)
        # Ease toward a nearby target. Convex steps stay inside the radius, and
        # the half-meter cap prevents large jumps between five-second updates.
        dx, dy = (self.goal_x - self.x) * 0.18, (self.goal_y - self.y) * 0.18
        scale = min(1.0, 0.5 / max(math.hypot(dx, dy), 1e-12))
        self.x += dx * scale
        self.y += dy * scale
        distance = math.hypot(self.x, self.y) / EARTH_RADIUS_M
        bearing = math.atan2(self.x, self.y)
        # Rotate a unit vector in the anchor's local north/east frame. This
        # remains well-conditioned at the poles and across the date line.
        sin_lat, cos_lat = math.sin(self.latitude), math.cos(self.latitude)
        sin_lon, cos_lon = math.sin(self.longitude), math.cos(self.longitude)
        north, east = math.cos(bearing), math.sin(bearing)
        x = math.cos(distance) * cos_lat * cos_lon + math.sin(distance) * (-north * sin_lat * cos_lon - east * sin_lon)
        y = math.cos(distance) * cos_lat * sin_lon + math.sin(distance) * (-north * sin_lat * sin_lon + east * cos_lon)
        z = math.cos(distance) * sin_lat + math.sin(distance) * north * cos_lat
        return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))
