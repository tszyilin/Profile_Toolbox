import math


def height_profile(samples):
    return samples


def slope_percent_profile(samples):
    """Slope as a percentage, averaged from the segments on either side of
    each point (matches profiletool's smoothing behaviour)."""
    n = len(samples)
    out = []
    for i in range(n):
        d, z, ok = samples[i]
        if not ok:
            out.append((d, z, False))
            continue
        slopes = []
        if i > 0 and samples[i - 1][2]:
            d0, z0, _ = samples[i - 1]
            if d != d0:
                slopes.append((z - z0) / (d - d0))
        if i < n - 1 and samples[i + 1][2]:
            d1, z1, _ = samples[i + 1]
            if d1 != d:
                slopes.append((z1 - z) / (d1 - d))
        slope_pct = (sum(slopes) / len(slopes) * 100) if slopes else 0.0
        out.append((d, slope_pct, True))
    return out


def slope_degrees_profile(samples):
    return [
        (d, math.degrees(math.atan(s / 100.0)), ok)
        for d, s, ok in slope_percent_profile(samples)
    ]


PROFILE_TYPES = {
    'Height': (height_profile, 'Elevation'),
    'Slope (%)': (slope_percent_profile, 'Slope (%)'),
    'Slope (°)': (slope_degrees_profile, 'Slope (°)'),
}
