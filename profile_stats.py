"""Summary statistics for a sampled profile.

Each `samples` argument is the list of (distance, elevation, ok) tuples
produced by the raster/vector samplers; points flagged `ok=False` are gaps
and are ignored here.
"""


def _trapz(ys, xs):
    return sum(
        (xs[i + 1] - xs[i]) * (ys[i + 1] + ys[i]) / 2.0
        for i in range(len(xs) - 1)
    )


def equal_area_slope(distances_km, elevations):
    """Slope (m/km) of the line that ties to the downstream elevation and
    splits the profile into equal cut and fill areas.

    Mirrors 01_EAS/equal_area_slope_v4.py, but solved analytically: with
    L(x) = c + (z_end - c) * x / X, balancing cut against fill means
    integral(L) == integral(z), which gives c = 2 * integral(z) / X - z_end.
    """
    span = distances_km[-1] - distances_km[0]
    if span <= 0:
        return None
    z_end = elevations[-1]
    intercept = 2.0 * _trapz(elevations, distances_km) / span - z_end
    return (z_end - intercept) / span


def compute_stats(samples):
    """Returns a dict of profile statistics, or None if there is nothing
    valid to summarise."""
    valid = [(d, z) for d, z, ok in samples if ok]
    if len(valid) < 2:
        return None

    distances = [d for d, _z in valid]
    elevations = [z for _d, z in valid]

    length = distances[-1] - distances[0]
    if length <= 0:
        return None

    max_z = max(elevations)
    min_z = min(elevations)
    max_at = distances[elevations.index(max_z)]
    min_at = distances[elevations.index(min_z)]

    # End-to-end gradient, matching the "average slope" of the EAS tool.
    mean_slope = (elevations[-1] - elevations[0]) / length

    distances_km = [d / 1000.0 for d in distances]
    eas = equal_area_slope(distances_km, elevations)

    return {
        'length': length,
        'max_z': max_z,
        'max_at': max_at,
        'min_z': min_z,
        'min_at': min_at,
        'mean_slope_pct': mean_slope * 100.0,
        'mean_slope_m_per_km': mean_slope * 1000.0,
        'eas_m_per_km': eas,
    }
