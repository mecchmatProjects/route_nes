"""Route map drawing using osmnx / networkx / matplotlib.

Emulates the draw_routes() style from route_finde_exampler.py:
  - lightgray base road network
  - CSS4 color cycling for route segments
  - red square for depot (technician home)
  - green circles for job stops
  - road-following paths via nx.shortest_path
"""

from __future__ import annotations

import osmnx as ox
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

from nes_dispatch.data.models import Job, Technician, RouteResult

# ── osmnx speed settings ───────────────────────────────────────────────────
ox.settings.use_cache = True
ox.settings.log_console = False


# ── Nearest-node lookup (avoids scikit-learn dependency) ────────────────────

def _nearest_node(G: nx.MultiDiGraph, lon: float, lat: float) -> int:
    """Return the graph node closest to (lon, lat) using brute-force search."""
    best, best_d = None, float("inf")
    for node, data in G.nodes(data=True):
        d = (data["x"] - lon) ** 2 + (data["y"] - lat) ** 2
        if d < best_d:
            best, best_d = node, d
    return best


# ── Graph helpers ───────────────────────────────────────────────────────────

_graph_cache: dict[str, nx.MultiDiGraph] = {}


def _graph_for_coords(
    lats: list[float], lons: list[float], buffer_m: int = 500,
) -> nx.MultiDiGraph:
    """Return a (cached) road graph that covers the given lat/lon points.

    Uses ``ox.graph_from_point`` with a radius large enough to cover all
    points plus *buffer_m* metres of padding.  Much faster than bbox queries
    because it avoids Overpass API sub-division.
    """
    import time
    from math import radians, cos, sqrt

    center_lat = (max(lats) + min(lats)) / 2
    center_lon = (max(lons) + min(lons)) / 2

    # Approximate max distance from centre to any point (metres)
    dlat_m = (max(lats) - min(lats)) / 2 * 111_320
    dlon_m = (max(lons) - min(lons)) / 2 * 111_320 * cos(radians(center_lat))
    radius_m = int(sqrt(dlat_m**2 + dlon_m**2)) + buffer_m
    radius_m = max(radius_m, 1500)  # minimum useful radius

    key = f"{center_lat:.4f},{center_lon:.4f},{radius_m}"
    if key not in _graph_cache:
        print(f"    Fetching road graph  centre=({center_lat:.4f}, {center_lon:.4f})  "
              f"r={radius_m} m")
        for attempt in range(3):
            try:
                G = ox.graph_from_point(
                    (center_lat, center_lon), dist=radius_m, network_type="drive",
                )
                break
            except Exception as exc:
                wait = 2 ** attempt * 2
                print(f"    Overpass error ({exc}), retrying in {wait}s...")
                time.sleep(wait)
        else:
            raise RuntimeError(f"Failed to download graph after 3 attempts")
        _graph_cache[key] = G
        print(f"    {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
        time.sleep(1)  # small courtesy delay between Overpass requests
    return _graph_cache[key]


def load_road_graph(
    center_lat: float = 43.10,
    center_lon: float = -71.50,
    dist: int = 15000,
    network_type: str = "drive",
) -> nx.MultiDiGraph:
    """Download (or return cached) OSM road graph around a centre point."""
    key = f"{center_lat:.4f},{center_lon:.4f},{dist}"
    if key not in _graph_cache:
        print(f"  Downloading OSM road graph ({network_type})...")
        print(f"  centre=({center_lat:.4f}, {center_lon:.4f})  r={dist} m")
        G = ox.graph_from_point(
            (center_lat, center_lon), dist=dist, network_type=network_type,
        )
        _graph_cache[key] = G
        print(f"  Graph loaded: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    return _graph_cache[key]


# ── Sorted CSS4 colour palette ─────────────────────────────────────────────

def _sorted_colors() -> list[str]:
    colors = sorted(
        mcolors.CSS4_COLORS,
        key=lambda c: tuple(mcolors.rgb_to_hsv(mcolors.to_rgb(c))),
    )
    # drop very light / white colours that are invisible on a light base map
    return [c for c in colors if sum(mcolors.to_rgb(c)) < 2.5]


_COLORS: list[str] | None = None


def _get_colors() -> list[str]:
    global _COLORS
    if _COLORS is None:
        _COLORS = _sorted_colors()
    return _COLORS


# ── Single-route drawing ───────────────────────────────────────────────────

def draw_route(
    G: nx.MultiDiGraph,
    route: RouteResult,
    tech: Technician,
    jobs_lookup: dict[str, Job],
    *,
    show: bool = True,
    save_path: str | None = None,
) -> None:
    """Draw one route on the road network, styled after route_finde_exampler.py."""
    colors = _get_colors()

    depot_lon, depot_lat = tech.home_lon, tech.home_lat

    # Collect stop coords in visit order
    stops: list[tuple[float, float, str]] = []  # (lon, lat, job_id)
    for jid in route.visited_job_ids:
        job = jobs_lookup[jid]
        stops.append((job.longitude, job.latitude, jid))

    if not stops:
        return

    # Base map
    fig, ax = ox.plot_graph(
        G, show=False, close=False, edge_color="lightgray", node_size=0,
    )

    # Depot marker (red square)
    ax.scatter(
        depot_lon, depot_lat,
        c="red", s=120, alpha=0.9, edgecolor="k", marker="s",
        label="Depot", zorder=5,
    )

    # Stop markers (green circles)
    for idx, (lon, lat, jid) in enumerate(stops):
        ax.scatter(
            lon, lat,
            c="green", s=70, alpha=0.8, edgecolor="k", marker="o",
            zorder=5,
        )
        ax.annotate(
            f" {idx+1}", (lon, lat),
            fontsize=7, color="white", fontweight="bold",
            zorder=6,
        )

    # Map coords → nearest graph nodes
    depot_node = _nearest_node(G, depot_lon, depot_lat)
    stop_nodes = [_nearest_node(G, lon, lat) for lon, lat, _ in stops]

    # Draw road-following segments: depot → stop1 → stop2 → ... → depot
    prev_node = depot_node
    waypoints = stop_nodes + [depot_node]  # close the loop

    for seg_idx, cur_node in enumerate(waypoints):
        is_return = (seg_idx == len(waypoints) - 1)
        color = "red" if is_return else colors[seg_idx % len(colors)]
        lw = 5 if is_return else 4

        try:
            path = nx.shortest_path(G, prev_node, cur_node, weight="length")
        except nx.NetworkXNoPath:
            print(f"    No road path: node {prev_node} → {cur_node}")
            prev_node = cur_node
            continue

        ox.plot_graph_route(
            G, path, ax=ax,
            route_color=color, route_linewidth=lw,
            orig_dest_size=0, show=False, close=False,
        )
        prev_node = cur_node

    title = (
        f"Route: {tech.name} ({route.tech_id}) — {route.vehicle_id} — {route.day}  "
        f"[{len(route.visited_job_ids)} stops, "
        f"{route.total_distance_m/1000:.1f} km, "
        f"{route.total_time_min:.0f} min]"
    )
    ax.set_title(title, fontsize=10, color="white")
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"    Saved: {save_path}")

    if show:
        plt.show()
    else:
        plt.close(fig)


# ── Draw all routes ────────────────────────────────────────────────────────

def draw_all_routes(
    routes: list[RouteResult],
    technicians: list[Technician],
    jobs_lookup: dict[str, Job],
    *,
    graph: nx.MultiDiGraph | None = None,
    show: bool = True,
    save_dir: str | None = None,
) -> None:
    """Draw every route on the road network.

    Parameters
    ----------
    graph : optional pre-loaded graph (applies to ALL routes).
            If None, a small per-route graph is downloaded automatically.
    show  : if True, call plt.show() per route (interactive).
    save_dir : if set, save PNGs to this directory instead of showing.
    """
    import os

    tech_map = {t.tech_id: t for t in technicians}

    if save_dir:
        os.makedirs(save_dir, exist_ok=True)

    for route in sorted(routes, key=lambda r: (r.day, r.tech_id)):
        if not route.visited_job_ids:
            continue
        tech = tech_map[route.tech_id]

        # Per-route graph (small bbox → fast download)
        if graph is None:
            lats = [tech.home_lat] + [jobs_lookup[j].latitude for j in route.visited_job_ids]
            lons = [tech.home_lon] + [jobs_lookup[j].longitude for j in route.visited_job_ids]
            G = _graph_for_coords(lats, lons)
        else:
            G = graph

        sp = None
        if save_dir:
            fname = f"route_{route.day}_{route.tech_id}_{route.vehicle_id}.png"
            sp = os.path.join(save_dir, fname)
        print(f"  Drawing {route.tech_id}/{route.vehicle_id}/{route.day} "
              f"({len(route.visited_job_ids)} stops)...")
        draw_route(
            G, route, tech, jobs_lookup,
            show=show and not save_dir,
            save_path=sp,
        )
