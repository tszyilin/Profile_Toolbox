# -*- coding: utf-8 -*-
"""Summary statistics for a single sampled profile.

Feeds the "Statistics" panel on the Profile tab. Kept dependency-free (no
numpy/scipy) so the panel always works, whatever is installed alongside QGIS.
"""

import math


def _clean(distances, elevations):
    """Pairs up distance/elevation, dropping None and NaN elevations.

    `distances`/`elevations` may be lists or numpy arrays, so they are never
    tested for truthiness directly.
    """
    if distances is None or elevations is None:
        return []
    out = []
    for d, z in zip(distances, elevations):
        if d is None or z is None:
            continue
        try:
            d = float(d)
            z = float(z)
        except (TypeError, ValueError):
            continue
        if math.isnan(d) or math.isnan(z):
            continue
        out.append((d, z))
    return out


def _trapz(ys, xs):
    return sum(
        (xs[i + 1] - xs[i]) * (ys[i + 1] + ys[i]) / 2.0
        for i in range(len(xs) - 1)
    )


def equal_area_slope(distances_km, elevations):
    """Slope (m/km) of the line tied to the downstream elevation that splits
    the profile into equal cut and fill areas.

    Solved analytically rather than numerically: for
    L(x) = c + (z_end - c) * x / X, equal cut and fill means
    integral(L) == integral(z), hence c = 2 * integral(z) / X - z_end.
    """
    span = distances_km[-1] - distances_km[0]
    if span <= 0:
        return None
    z_end = elevations[-1]
    intercept = 2.0 * _trapz(elevations, distances_km) / span - z_end
    return (z_end - intercept) / span


def compute_stats(distances, elevations):
    """Returns a dict of profile statistics, or None if there is not enough
    valid data to summarise.

    "gradient" is the end-to-end grade (elevation change over length); the
    equal-area slope is reported separately, in m/km.
    """
    points = _clean(distances, elevations)
    if len(points) < 2:
        return None

    ds = [d for d, _z in points]
    zs = [z for _d, z in points]

    length = ds[-1] - ds[0]
    if length <= 0:
        return None

    max_z = max(zs)
    min_z = min(zs)

    # End-to-end elevation change and gradient.
    dz = zs[-1] - zs[0]
    gradient = dz / length

    return {
        "length": length,
        "dz": dz,
        "max_z": max_z,
        "max_at": ds[zs.index(max_z)],
        "min_z": min_z,
        "min_at": ds[zs.index(min_z)],
        "gradient_m_per_m": gradient,
        "gradient_pct": gradient * 100.0,
        "eas_m_per_km": equal_area_slope([d / 1000.0 for d in ds], zs),
    }


def segment_stats(distances, elevations, x0, x1):
    """Statistics for the slice of the profile between chainages x0 and x1.

    The chainages may be given in either order. Returns the same keys as
    compute_stats, plus "start" and "end", or None if fewer than two valid
    samples fall inside the range.
    """
    if x0 is None or x1 is None:
        return None
    lo, hi = (x0, x1) if x0 <= x1 else (x1, x0)

    points = [p for p in _clean(distances, elevations) if lo <= p[0] <= hi]
    if len(points) < 2:
        return None

    stats = compute_stats([d for d, _z in points], [z for _d, z in points])
    if stats is None:
        return None

    stats["start"] = points[0][0]
    stats["end"] = points[-1][0]
    return stats
