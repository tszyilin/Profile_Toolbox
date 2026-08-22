# -*- coding: utf-8 -*-
"""Equal Area Slope computation.

Ported from the standalone tkinter tool `equal_area_slope_v4.py`. Only the
core processing function is kept here; the GUI lives in
`ui/dlg_equal_area_slope.py`.
"""

import os
import datetime


def compute_equal_area_slope(distances_m, elevations):
    """Compute EAS on a single profile already in memory.

    Parameters
    ----------
    distances_m : sequence of float
        Distance along the profile, in metres, monotonically increasing.
    elevations : sequence of float
        Elevation at each distance, in metres. NaNs are dropped.

    Returns
    -------
    dict with keys: distances_km, elevations, equal_area_line, average_line,
    equal_area_slope (m/km), average_slope (m/km), area_cut, area_fill,
    length_km, intercept.
    """
    import numpy as np
    from scipy.optimize import minimize

    distances_m = np.asarray(distances_m, dtype=float)
    elevations = np.asarray(elevations, dtype=float)
    valid = ~np.isnan(elevations)
    elevations = elevations[valid]
    distances_km = distances_m[valid] / 1000.0

    if len(distances_km) < 2:
        raise ValueError("Need at least 2 valid profile points.")

    downstream_elevation = elevations[-1]

    def area_difference(intercept):
        slope = (downstream_elevation - intercept) / distances_km[-1]
        line = intercept + slope * distances_km
        area_cut = np.trapz(np.maximum(line - elevations, 0), distances_km)
        area_fill = np.trapz(np.maximum(elevations - line, 0), distances_km)
        return abs(area_cut - area_fill)

    result = minimize(area_difference, float(np.mean(elevations)), tol=1e-10)
    intercept = float(result.x[0])
    slope = (downstream_elevation - intercept) / distances_km[-1]
    equal_area_line = intercept + slope * distances_km

    area_cut = float(np.trapz(np.maximum(equal_area_line - elevations, 0), distances_km))
    area_fill = float(np.trapz(np.maximum(elevations - equal_area_line, 0), distances_km))
    average_slope = (elevations[-1] - elevations[0]) / (distances_km[-1] - distances_km[0])
    average_line = elevations[0] + average_slope * distances_km

    return {
        'distances_km': distances_km,
        'elevations': elevations,
        'equal_area_line': equal_area_line,
        'average_line': average_line,
        'equal_area_slope': float(slope),
        'average_slope': float(average_slope),
        'area_cut': area_cut,
        'area_fill': area_fill,
        'length_km': float(distances_km[-1]),
        'intercept': intercept,
    }


def run_equal_area_slope(line_shapefile, raster_file, id_header, out_fol,
                         out_file, interval=10):
    """Compute and plot the equal-area slope line for each stream in the shapefile.

    Parameters
    ----------
    line_shapefile : str
        Path to the input line (streamline) shapefile.
    raster_file : str
        Path to the input elevation raster (e.g. a DEM GeoTIFF).
    id_header : str
        Name of the shapefile attribute field used as the unique identifier
        for naming output plots. If blank or not found, the row index is used.
    out_fol : str
        Output folder for the generated plots.
    out_file : str
        Output filename prefix.
    interval : float
        Sampling interval along the line, in metres.
    """
    import geopandas as gpd
    import rasterio
    import numpy as np
    from shapely.geometry import LineString
    import matplotlib.pyplot as plt
    from scipy.optimize import minimize

    os.makedirs(out_fol, exist_ok=True)
    run_time = datetime.datetime.now()
    log_path = os.path.join(
        out_fol, f'{out_file}_log_{run_time:%Y%m%d_%H%M%S}.txt')
    log_lines = []

    def log(message=''):
        print(message)
        log_lines.append(str(message))

    log('=' * 70)
    log('Equal Area Slope Tool - run log')
    log('=' * 70)
    log(f'Run date/time        : {run_time:%Y-%m-%d %H:%M:%S}')
    log('')
    log('Inputs')
    log('-' * 70)
    log(f'Input shapefile      : {line_shapefile}')
    log(f'Input raster (DEM)   : {raster_file}')
    log(f'Unique identifier    : {id_header if id_header else "(row index)"}')
    log(f'Output folder        : {out_fol}')
    log(f'Output file prefix   : {out_file}')
    log(f'Sampling interval (m): {interval}')
    log('')

    lines_gdf = gpd.read_file(line_shapefile)
    raster = rasterio.open(raster_file)

    if lines_gdf.crs != raster.crs:
        lines_gdf = lines_gdf.to_crs(raster.crs)

    id_header = (id_header or '').strip()
    if id_header and id_header not in lines_gdf.columns:
        log(f"Warning: identifier field '{id_header}' not found in shapefile. "
            f"Available fields: {list(lines_gdf.columns)}. Falling back to row index.")
        id_header = ''

    log(f'Features in shapefile: {len(lines_gdf)}')
    log('')
    log('Results')
    log('-' * 70)

    results = []

    for idx, row in lines_gdf.iterrows():
        line = row.geometry
        if not isinstance(line, LineString):
            log(f"Geometry at index {idx} is not a LineString. Skipped.")
            continue

        if id_header:
            uid = row[id_header]
            if uid is None or (isinstance(uid, float) and np.isnan(uid)) or str(uid).strip() == '':
                uid = idx
        else:
            uid = idx
        uid_str = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in str(uid))

        total_length_meters = line.length
        total_length_km = total_length_meters / 1000

        num_points = int(total_length_meters // interval) + 1
        distances = np.linspace(0, total_length_meters, num_points)

        points = [line.interpolate(distance) for distance in distances]
        coords = [(point.x, point.y) for point in points]

        elevations = [val[0] if val else np.nan for val in raster.sample(coords)]
        elevations = np.array(elevations)

        valid = ~np.isnan(elevations)
        elevations = elevations[valid]
        distances_km = distances[valid] / 1000

        downstream_elevation = elevations[-1]

        def area_difference(intercept):
            slope = (downstream_elevation - intercept) / distances_km[-1]
            equal_area_line = intercept + slope * distances_km
            area_cut = np.trapz(np.maximum(equal_area_line - elevations, 0), distances_km)
            area_fill = np.trapz(np.maximum(elevations - equal_area_line, 0), distances_km)
            return abs(area_cut - area_fill)

        initial_guess = np.mean(elevations)
        result = minimize(area_difference, initial_guess, tol=1e-10)
        intercept = result.x[0]

        slope = (downstream_elevation - intercept) / distances_km[-1]
        equal_area_line = intercept + slope * distances_km

        area_cut = np.trapz(np.maximum(equal_area_line - elevations, 0), distances_km)
        area_fill = np.trapz(np.maximum(elevations - equal_area_line, 0), distances_km)

        average_slope = (elevations[-1] - elevations[0]) / (distances_km[-1] - distances_km[0])

        log(f'Line {uid} length: {total_length_km:.2f} km')
        log(f'Equal area slope: {slope:.2f} m/km')
        log(f'Average slope: {average_slope:.2f} m/km')
        log(f'Area cut (upstream): {area_cut:.4f}, Area fill (downstream): {area_fill:.4f}')

        results.append({
            'id': uid,
            'length_km': total_length_km,
            'equal_area_slope': slope,
            'average_slope': average_slope,
            'area_cut': area_cut,
            'area_fill': area_fill,
        })

        plt.figure(figsize=(10, 6))
        plt.plot(distances_km, elevations, label='Longitudinal Profile', color='black')
        plt.plot(distances_km, equal_area_line, label='Equal Area Slope Line', linestyle='--', color='red')

        average_line = elevations[0] + average_slope * distances_km
        plt.plot(distances_km, average_line, linestyle=':', color='black', label='Average Slope Line')

        plt.fill_between(distances_km, elevations, equal_area_line,
                         where=(elevations > equal_area_line), color='purple', alpha=0.3,
                         label='Area below (cut - upstream)')
        plt.fill_between(distances_km, equal_area_line, elevations,
                         where=(equal_area_line > elevations), color='green', alpha=0.3,
                         label='Area above (fill - downstream)')

        plt.xlabel('Distance along main stream (km)')
        plt.ylabel('Elevation (m)')
        plt.title(f'Longitudinal Profile with Equal Area and Average Slope Lines ({uid})')
        plt.legend()
        plt.grid(True)

        plot_path = os.path.join(out_fol, f'{out_file}_{uid_str}.png')
        plt.savefig(plot_path, dpi=300)
        plt.close()
        log(f'Saved plot: {plot_path}')
        log('')

    raster.close()

    log('-' * 70)
    log(f'Processing complete. {len(results)} line(s) processed.')
    try:
        with open(log_path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(log_lines) + '\n')
        print(f'Saved log: {log_path}')
    except Exception as exc:
        print(f'Warning: could not write log file to {log_path}: {exc}')

    return results
