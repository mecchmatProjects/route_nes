#!/usr/bin/python3 env
from math import radians, cos, sin, sqrt, atan2, exp
from collections import defaultdict
import csv
import json
import time
import os
import fnmatch

import numpy as np
import osmnx as ox
import networkx as nx
import pandas as pd
import matplotlib.pyplot as plt
from shapely.geometry import shape, Point
import geopandas as gpd


from route_finder_sa import *
from route_finder_MILP import *
from route_finder_BFS import *

TAXICAB = False
if TAXICAB:
    import taxicab


DEBUG = True  # False  #
# If we already have geodata image we don't need to recreate it
HAVE_GEODATA = False  # True  #
# If we already have distance matrix for the transport, we don't need to recreate it
HAVE_DIST_MATRIX = True  # False  #

# Use divide and conquer strategy for distance matrix generation
USE_SPLIT_MATRIX = True  # True  #

# Whether to show resulting path Map
SHOW_FOUND_PATH = True  # False

# Locations data file
CHECKPOINTS_LOCATIONS = "rome_coordinates_only.csv"  # "data3km.csv"  #  "data.txt"  # "data_test.txt"  # "data_test2.csv"  #      "data_new.txt"  #    "data_roma2.csv"  #       #
# GeoJSON regions file
GEOJSON_FILE = "Areas.geojson"

START_TEST = 5  # The index of the test to work on
INDEX_TRANSPORT = 1  # 0 - walking, 1 - auto

# Methods using
USE_STREET_FILL = False  # True  #
HEURISTIC2 = False
BRUTEFORCE = False  # True  # False  #
MILP_RUN = False  # True  #
GREEDY_HEURISTICS = True
SIMULATED_ANNEALING = True

# Limit of calculation time in seconds
TIME_CALCULATION_LIMIT = 120

total_time_work = 0
round_calculations = TIME_CALCULATION_LIMIT

# Loop for cluster characteristics
ITER_FILTER_MAX = 3
MIN_CHECKPOINTS = 10
RADIUS_ADD = 250

# Maximum number of inspections
P = 20  # 14  #

# Whether to show maps
SHOW_ALL_MAPS = True  # False  #
# PARAMETERS set
OSMNX_TYPES = ["all", "all_public", "bike", "drive", "drive_service", "walk"]
TRANSPORT_TYPES = ("walk", "drive")  # "BIKE",

# y - latitude, x -longitude,
TEST_START = {
    1: (41.90162000000000, 12.48078000000000),
    6: (41.90531339275057, 12.49223435987536),
    2: (41.9089336283689, 12.495792317546838),
    3: (41.898184552402924, 12.483071460626425),
    4: (41.9094431086078, 12.478017188711103),
    5: (41.90458082333292, 12.48604197092002),
    7: (41.90251100000012, 12.47745800000011),
    8: (41.89567489637171, 12.49169281914634),
    9: (41.90220214842297, 12.49607715472886),
    10: (41.88220580343056, 12.47656522589266),
}
# We should not go further from the start
CLUSTER_RADIUS = [200, 500]
# Maximum Distance Between Inspections:
INSPECT_RADIUS = [200, 500]

# Maximum time of inspections lap (minutes)
Tmax = 6 * 60
# Inspection time (minutes)
TI = 20

# Speed of the transports
KMHR_MMIN = 1000.0 / 60  # to m/min
V = [4 * KMHR_MMIN, 30 * KMHR_MMIN]

# Cost of meter per transport
KM_M = 0.001  # Meters in 1 km division
C = [0.55 * KM_M, 0.9 * KM_M]


# print(V, C)

# # Create road network graph
# map_g = ox.graph_from_place('Rome, Italy', network_type='drive')
# # OSM data are sometime incomplete so we use the speed module of osmnx to add missing edge speeds and travel times
# map_g = ox.add_edge_speeds(map_g)
# map_g = ox.add_edge_travel_times(map_g)
# # Plot the graph
# fig, ax = ox.plot_graph(map_g, figsize=(10, 10), node_size=0, edge_color='y', edge_linewidth=0.2)


def delete_files_by_template(folder_path, name_template):
    """Deletes files in a folder matching a name template.

    Args:
        folder_path (str): Path to the folder.
        name_template (str):  Filename pattern to match (e.g., "*.txt", "data_*.log").
    """
    try:
        for filename in os.listdir(folder_path):
            if fnmatch.fnmatch(filename, name_template):
                file_path = os.path.join(folder_path, filename)
                os.remove(file_path)
                print(f"Deleted: {file_path}")
    except FileNotFoundError:
        print(f"Error: Folder not found: {folder_path}")
    except Exception as e:
        print(f"An error occurred: {e}")


def find_SEPRAG(point_x: float, point_y: float, filename: str = GEOJSON_FILE):
    """
    Find SEPRAG district number of the given point
    :param point_x: x -coordinate of the point
    :param point_y: y -coordinate of the point
    :param filename: name of GEOJSON file
    :return: number of the SEPRAG
    """

    # load GeoJSON file containing sectors
    with open(filename) as f:
        geo_data = json.load(f)
    # construct point based on lon/lat
    point = Point(point_x, point_y)

    # check each polygon to see if it contains the point
    for feature in geo_data["features"]:
        if feature["geometry"]["type"] == "Polygon":
            polygon = shape(feature["geometry"])
            # print(polygon)

            if polygon.contains(point):
                # print("Point is within polygon:", feature['properties']['SEPRAG'])
                return feature["properties"]["SEPRAG"]

        elif feature["geometry"]["type"] == "MultiPolygon":
            for polygon_coords in feature["geometry"]["coordinates"]:
                # print(polygon_coords)
                polygon = shape({"type": "Polygon", "coordinates": polygon_coords})
                # print(polygon)
                if polygon.contains(point):
                    # print("Point is within polygon:", feature['properties']['SEPRAG'])
                    return feature["properties"]["SEPRAG"]

    return None


#
# SEPRAG_VALUE = find_SEPRAG(TEST_START[START_TEST][1], TEST_START[START_TEST][0])
# print("SEPRAG of ", TEST_START[START_TEST], "is ", SEPRAG_VALUE)


center = TEST_START[START_TEST]
name_test = START_TEST
# if isinstance(START_TEST, int):
#     center = TEST_START[START_TEST]
#     name_test = START_TEST

start_time = time.perf_counter()
max_rad = max(CLUSTER_RADIUS) + (ITER_FILTER_MAX + 0.5) * RADIUS_ADD  # meters

if not HAVE_GEODATA:
    G = []
    for i, mode in enumerate(TRANSPORT_TYPES):
        G1 = ox.graph.graph_from_point(
            center, dist=max_rad, network_type=mode, simplify=True
        )
        G1 = ox.add_edge_bearings(G1)
        G.append(G1)
else:
    G = []
    for i, mode in enumerate(TRANSPORT_TYPES):
        G1 = ox.load_graphml(f"MAP_{name_test}_{TRANSPORT_TYPES[i]}.graphml")
        G1 = ox.add_edge_bearings(G1)
        G.append(G1)

        if DEBUG:
            print(ox.stats.basic_stats(G[i]))

end_time = time.perf_counter()
total_time_work += end_time - start_time
if HAVE_GEODATA:
    print("Loadin image from disk takes ", end_time - start_time, "sec")
else:
    print("Loadin image from OSMNX takes ", end_time - start_time, "sec")

# Probably don't need this
# OSM data are sometime incomplete, so we use the speed module of osmnx to add missing edge speeds and travel times
# map_g = ox.add_edge_speeds(map_g)
# map_g = ox.add_edge_travel_times(map_g)

# Save graph to disk if you want to reuse it
for i, g in enumerate(G):
    if not HAVE_GEODATA:
        ox.save_graphml(g, f"MAP_{name_test}_{TRANSPORT_TYPES[i]}.graphml")
    # Plot the graph
    if SHOW_ALL_MAPS:
        fig, ax = ox.plot_graph(
            g, figsize=(10, 10), node_size=0, edge_color="y", edge_linewidth=0.2
        )


def assign_SEPRAG_geopandas(
    df: pd.DataFrame, x_col: str, y_col: str, geojson_path: str
) -> pd.Series:
    """
    Efficiently assign SEPRAG district to each row in the DataFrame using GeoPandas spatial join.

    :param df: DataFrame with point coordinates.
    :param x_col: Name of the longitude column.
    :param y_col: Name of the latitude column.
    :param geojson_path: Path to GeoJSON file with SEPRAG zones.
    :return: Series with SEPRAG zone values.
    """

    # Step 1: Load SEPRAG zones as a GeoDataFrame
    seprag_gdf = gpd.read_file(geojson_path)

    # Step 2: Create a GeoDataFrame from your coordinates
    geometry = [Point(xy) for xy in zip(df[x_col], df[y_col])]
    points_gdf = gpd.GeoDataFrame(df.copy(), geometry=geometry, crs=seprag_gdf.crs)

    # Step 3: Spatial join
    joined = gpd.sjoin(
        points_gdf, seprag_gdf[["SEPRAG", "geometry"]], how="left", predicate="within"
    )

    # Step 4: Return the SEPRAG column
    return joined["SEPRAG"]


# Read files for checkpoints
def load_locations(filename: str, use_seprag: bool = True):
    """
    Create Pandas Dataframe from csv or txt file
    :param filename: - name of the file (str)
    :param use_seprag: if we use seprag into output
    :return: dataframe
    """
    if filename.endswith("txt"):
        df = pd.read_csv(filename, sep="\t", decimal=",").dropna()
        df["name"] = df["indirizzo"].astype(str)
        df["latitude"] = (
            df["latitudine"].astype(str).str.replace(",", ".").astype(float)
        )
        df["longitude"] = (
            df["longitudine"].astype(str).str.replace(",", ".").astype(float)
        )
        df["revenues"] = df["Revenues"].astype(float)
        df.drop(["Revenues"], axis="columns", inplace=True)
    elif filename.endswith("csv"):
        df = pd.read_csv(filename).dropna()
        df["name"] = df["indirizzo"].astype(str)
        df["latitude"] = df["latitudine"].astype(str).str.replace(",", "")
        df["latitude"] = (
            df["latitude"].astype(str).str[:2]
            + "."
            + df["latitude"].astype(str).str[2:]
        )
        df["latitude"] = df["latitude"].astype(float)
        df["longitude"] = df["longitudine"].astype(str).str.replace(",", "")
        df["longitude"] = (
            df["longitude"].astype(str).str[:2]
            + "."
            + df["longitude"].astype(str).str[2:]
        )
        df["longitude"] = df["longitude"].astype(float)
        df["revenues"] = df["revenues"].astype(float)
    else:
        print("Unsupported data format")
        return None

    df.drop(["latitudine", "longitudine", "indirizzo"], axis="columns", inplace=True)

    if use_seprag:
        df["region"] = assign_SEPRAG_geopandas(
            df, "longitude", "latitude", GEOJSON_FILE
        )

    df.dropna(inplace=True)
    print(df[:5])
    return df


# Prepare coordinate tuples
def extract_coordinates(df):
    return [(row["latitude"], row["longitude"]) for _, row in df.iterrows()]


def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate haversine distance
    :param lat1: latitude of the first position (float)
    :param lon1: longitude of the first position (float)
    :param lat2: latitude of the second position (float)
    :param lon2: longitude of the second position (float)
    :return: hoversine (geoid) distance
    """
    R = 6371000  # Earth radius in meters
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lon2 - lon1)

    leg = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    if leg < 0:
        # print("leg of ", lat1, lon1, lat2, lon2,":", leg)
        leg = 0
    elif leg > 1:
        # print("leg2 of ", lat1, lon1, lat2, lon2,":", leg)
        leg = 1
    angle2 = 2 * atan2(sqrt(leg), sqrt(1 - leg))
    return R * angle2


def real_distance(lat1, lon1, lat2, lon2, street1, street2, transport_mode):
    """
    Calculate haversine distance
    :param lat1: latitude of the first position (float)
    :param lon1: longitude of the first position (float)
    :param lat2: latitude of the second position (float)
    :param lon2: longitude of the second position (float)
    :return: distance
    """
    global G

    node1, r1 = ox.distance.nearest_nodes(
        G[transport_mode], lon1, lat1, return_dist=True
    )
    node2, r2 = ox.distance.nearest_nodes(
        G[transport_mode], lon2, lat2, return_dist=True
    )

    if TAXICAB:
        route = taxicab.distance.shortest_path(
            G[transport_mode], (lat1, lon1), (lat2, lon2)
        )
        return route.length

    if street1 != street2:
        try:
            return (
                nx.shortest_path_length(
                    G[transport_mode], node1, node2, weight="length"
                )
                + r1
                + r2
            )
        except nx.NetworkXNoPath:
            print("No way from ", street1, "to ", street2, ":", lat1, lon1, lat2, lon2)
            return np.Inf
    else:
        return haversine(lat1, lon1, lat2, lon2)


def street_house_separate(address: str):
    """
    Separate Street name and House number form the address_lst
    House number is considered only first number
    :param address: string of the address_lst
    :return: tuple of street name (str) and house number (int)
    """

    street_name = ""
    house = 0
    is_number = False
    for c in address:
        if is_number:
            if not c.isdigit():
                break
            house = 10 * house + int(c)
        else:
            if c.isdigit():
                is_number = True
                house = 10 * house + int(c)
            else:
                street_name += c
    # print(address_lst, street_name, house)
    return street_name, house


def get_matrix_distances(df: pd.DataFrame, transport_mode: int):
    """
    Create Matrix of distances from the dataframe of geolocations
    :param df: dataframe of geolocations
    :param transport_mode: integer to represent walk/drive modes of the map
    :param seprag[default=None]: the number of SEPRAG to filter outside points
    :return: list of distances
    """
    global G, V, INSPECT_RADIUS

    DEBUG_MATRIX = False  # True  #
    # G_proj = ox.project_graph(map_g[mode])
    # G_proj = ox.project_graph(map_g[mode], to_crs="EPSG:32633")  # Rome's UTM zone

    dist_matrix = []
    nodes_lst = []
    r_lst = []
    x_lst = []
    y_lst = []
    street_lst = []
    item_lst = []
    revenue_lst = []
    seprag_lst = []
    for id1, data_row in df.iterrows():
        # print(id1, data_row)
        coord_x, coord_y = data_row["longitude"], data_row["latitude"]
        if coord_x is None or coord_y is None:
            continue

        # seprag = find_SEPRAG(coord_x, coord_y)
        seprag = data_row["region"]

        # print(data_coord)
        try:
            data_node, r1 = ox.distance.nearest_nodes(
                G[transport_mode], coord_x, coord_y, return_dist=True
            )
            nodes_lst.append(data_node)
            r_lst.append(r1)
            x_lst.append(coord_x)
            y_lst.append(coord_y)
            street_name, _ = street_house_separate(data_row["name"])
            street_lst.append(street_name)
            item_lst.append(id1)
            revenue_lst.append(data_row["revenues"])
            seprag_lst.append(seprag)
            if DEBUG_MATRIX:
                print("Node:", data_node, r1, street_name)
        except ValueError as e:
            if DEBUG and DEBUG_MATRIX:
                print("Point:", coord_x, coord_y, data_row["name"], " is empty")
            # input()
            continue

    for i, node1, r1, x1, y1, s1, rev1, sep1 in zip(
        item_lst, nodes_lst, r_lst, x_lst, y_lst, street_lst, revenue_lst, seprag_lst
    ):
        for j, node2, r2, x2, y2, s2, rev2, sep2 in zip(
            item_lst,
            nodes_lst,
            r_lst,
            x_lst,
            y_lst,
            street_lst,
            revenue_lst,
            seprag_lst,
        ):
            if sep1 != sep2:
                continue
            if i == j:
                continue

            dist_haver = haversine(y1, x1, y2, x2)
            if dist_haver > INSPECT_RADIUS[transport_mode]:
                continue

            if DEBUG_MATRIX:
                print("Loop:", node2, r2, s2, node1, r1, s1)

            dist = dist_haver
            taxicab_fail = True
            if TAXICAB:
                try:
                    route_xy = taxicab.distance.shortest_path(
                        G[transport_mode], (y1, x1), (y2, x2)
                    )
                    dist = route_xy.length
                    taxicab_fail = False
                except Exception:
                    pass

            if taxicab_fail:
                if s1 != s2:
                    try:
                        dist = (
                            nx.shortest_path_length(
                                G[transport_mode], node1, node2, weight="length"
                            )
                            + r1
                            + r2
                        )
                    except nx.NetworkXNoPath:
                        if DEBUG and DEBUG_MATRIX:
                            print("No way from ", s1, "to ", s2, ":", x1, y1, x2, y2)
                else:
                    dist = abs(r1 - r2)

            price_item = dist * C[transport_mode]
            time_spent_item = dist / V[transport_mode]

            if dist <= INSPECT_RADIUS[transport_mode]:
                dist_matrix.append([i, j, dist, price_item, time_spent_item, rev2])
                # print(dist)
            else:
                if DEBUG and DEBUG_MATRIX:
                    print("No way from ", s1, "to ", s2, ":", x1, y1, x2, y2)
                    print(dist)
                    try:
                        route_xy = taxicab.distance.shortest_path(
                            G[transport_mode], (y2, x2), (y1, x1)
                        )
                        dist2 = route_xy.length
                        print(dist2)
                    except Exception:
                        dist2 = (
                            nx.shortest_path_length(
                                G[transport_mode], node1, node2, weight="length"
                            )
                            + r1
                            + r2
                        )
                        print(dist2)

    return dist_matrix


def get_matrix_distances2(df1: pd.DataFrame, df2: pd.DataFrame, transport_mode: int):
    """
    Create Matrix of distances from the dataframe of geolocations
    :param df: dataframe of geolocations
    :param transport_mode: integer to represent walk/drive modes of the map
    :param seprag[default=None]: the number of SEPRAG to filter outside points
    :return: list of distances
    """
    global G, V, INSPECT_RADIUS

    DEBUG_MATRIX = False  # True  #
    # G_proj = ox.project_graph(map_g[mode])
    # G_proj = ox.project_graph(map_g[mode], to_crs="EPSG:32633")  # Rome's UTM zone

    dist_matrix = []
    nodes_lst = []
    r_lst = []
    x_lst = []
    y_lst = []
    street_lst = []
    item_lst = []
    revenue_lst = []
    seprag_lst = []
    for id1, data_row in df1.iterrows():
        # print(id1, data_row)
        coord_x, coord_y = data_row["longitude"], data_row["latitude"]
        if coord_x is None or coord_y is None:
            continue

        # seprag = find_SEPRAG(coord_x, coord_y)
        seprag = data_row["region"]

        # print(data_coord)
        try:
            data_node, r1 = ox.distance.nearest_nodes(
                G[transport_mode], coord_x, coord_y, return_dist=True
            )
            nodes_lst.append(data_node)
            r_lst.append(r1)
            x_lst.append(coord_x)
            y_lst.append(coord_y)
            street_name, _ = street_house_separate(data_row["name"])
            street_lst.append(street_name)
            item_lst.append(id1)
            revenue_lst.append(data_row["revenues"])
            seprag_lst.append(seprag)
            if DEBUG_MATRIX:
                print("Node:", data_node, r1, street_name)
        except ValueError as e:
            if DEBUG and DEBUG_MATRIX:
                print("Point:", coord_x, coord_y, data_row["name"], " is empty")
            # input()
            continue

    nodes_lst2 = []
    r_lst2 = []
    x_lst2 = []
    y_lst2 = []
    street_lst2 = []
    item_lst2 = []
    revenue_lst2 = []
    seprag_lst2 = []
    for id2, data_row in df2.iterrows():
        # print(id1, data_row)
        coord_x, coord_y = data_row["longitude"], data_row["latitude"]
        if coord_x is None or coord_y is None:
            continue

        # seprag = find_SEPRAG(coord_x, coord_y)
        seprag = data_row["region"]

        # print(data_coord)
        try:
            data_node, r1 = ox.distance.nearest_nodes(
                G[transport_mode], coord_x, coord_y, return_dist=True
            )
            nodes_lst.append(data_node)
            r_lst2.append(r1)
            x_lst2.append(coord_x)
            y_lst2.append(coord_y)
            street_name, _ = street_house_separate(data_row["name"])
            street_lst2.append(street_name)
            item_lst2.append(id2)
            revenue_lst2.append(data_row["revenues"])
            seprag_lst2.append(seprag)
            if DEBUG_MATRIX:
                print("Node:", data_node, r1, street_name)
        except ValueError as e:
            if DEBUG and DEBUG_MATRIX:
                print("Point:", coord_x, coord_y, data_row["name"], " is empty")
            # input()
            continue

    for i, node1, r1, x1, y1, s1, rev1, sep1 in zip(
        item_lst, nodes_lst, r_lst, x_lst, y_lst, street_lst, revenue_lst, seprag_lst
    ):
        for j, node2, r2, x2, y2, s2, rev2, sep2 in zip(
            item_lst2,
            nodes_lst2,
            r_lst2,
            x_lst2,
            y_lst2,
            street_lst2,
            revenue_lst2,
            seprag_lst2,
        ):
            if sep1 != sep2:
                continue
            if i == j:
                continue

            dist_haver = haversine(x1, y1, x2, y2)
            if dist_haver > INSPECT_RADIUS[transport_mode]:
                continue

            if DEBUG_MATRIX:
                print("Loop:", node2, r2, s2, node1, r1, s1)

            dist = dist_haver
            taxicab_fail = True
            if TAXICAB:
                try:
                    route_xy = taxicab.distance.shortest_path(
                        G[transport_mode], (y1, x1), (y2, x2)
                    )
                    dist = route_xy.length
                    taxicab_fail = False
                except Exception:
                    if DEBUG and DEBUG_MATRIX:
                        print("No way from ", s1, "to ", s2, ":", x1, y1, x2, y2)
                    pass

            if taxicab_fail:
                if s1 != s2:
                    try:
                        dist = (
                            nx.shortest_path_length(
                                G[transport_mode], node1, node2, weight="length"
                            )
                            + r1
                            + r2
                        )
                    except nx.NetworkXNoPath:
                        if DEBUG and DEBUG_MATRIX:
                            print("No way from ", s1, "to ", s2, ":", x1, y1, x2, y2)
                        continue
                elif node1 == node2:
                    dist = abs(r1 - r2)
                else:
                    continue

            price_item = dist * C[transport_mode]
            time_spent_item = dist / V[transport_mode]

            if dist <= INSPECT_RADIUS[transport_mode]:
                dist_matrix.append([i, j, dist, price_item, time_spent_item, rev2])

    return dist_matrix


def get_matrix_split(name: str, num_splitted_files: int):

    df_result = pd.read_csv(f"distance_matr_{name}_part{0}.csv")
    for j in range(1, num_splitted_files + 1):
        df = pd.read_csv(f"distance_matr_{name}_parts{0}_{j}.csv")
        if df.empty:
            continue
        df_result = pd.concat([df_result, df], ignore_index=True)

    for i in range(1, num_splitted_files + 1):
        df = pd.read_csv(f"distance_matr_{name}_part{i}.csv")
        if df.empty:
            continue
        df_result = pd.concat([df_result, df], ignore_index=True)
        for j in range(i + 1, num_splitted_files + 1):
            if j == i:
                continue

            df = pd.read_csv(f"distance_matr_{name}_parts{i}_{j}.csv")
            if df.empty:
                continue

            df_result = pd.concat([df_result, df], ignore_index=True)

    delete_files_by_template(".", f"distance_matr_{name}_part*.csv")

    return df_result


def check_routes(
    route_lst: List[int],
    revenues_lst: List[float],
    cost: float,
    dist_matr,
    tau_lst: List[float],
    v: float,
):
    """
    Print the route_lst parameters
    :param route_lst: list of route_lst checkpoints
    :param revenues_lst: list of revenues_lst
    :param cost: cost per 1 meter of drive/walk
    :param dist_matr: numpy matrix representing distance matrix
    :param tau_lst: numpy array of inspection time per node
    :param v: speed of travelling per 1m
    :return: void
    """
    sum_t = 0
    sum_obj = 0

    for node, node_next in zip(route_lst[:-1], route_lst[1:]):
        price = cost * dist_matr[node, node_next]
        # print(dist_matr[node, node_next], node, node_next)
        t = tau_lst[node_next] + dist_matr[node, node_next] / v
        val = revenues_lst[node_next] - price
        sum_t += t
        sum_obj += val
        print(
            f"Revenue for point {node} is {val} = {revenues_lst[node_next]} - {price}, time: {sum_t}, Reward: {sum_obj}"
        )


def print_routes(
    route_lst: List[int],
    route_coordinates: List[Tuple[float, float]],
    nodes,
    revenues_lst: List[float],
    address_lst: List[str],
    file=None,
):
    """
    Print route_lst parameters into console/file
    :param route_lst: list of route_lst checkpoints
    :param route_coordinates: list of tuple of x,y node cooridnates
    :param nodes: NA
    :param revenues_lst: list of revenues_lst
    :param address_lst:
    :param file:
    :return:
    """
    for i, node in enumerate(route_lst):
        # print(f"Point {i} is {node} with coridinates ({route_coordinates[0]}, {route_coordinates[1]})")
        # print(f"{node}:({route_coordinates[node][0]}, {route_coordinates[node][1]}) -GEO node{nodes[i]}, ")
        print(
            f"{node}:({route_coordinates[node][0]}, {route_coordinates[node][1]})",
            file=file,
            end=";\t",
        )

    with open(
        f"output_{CHECKPOINTS_LOCATIONS[:-4]}_{START_TEST}.csv", "w", newline=""
    ) as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["point", "Address", "coordinates", "Revenues"])

        for i, node in enumerate(route_lst):
            data = [
                node,
                address_lst[node],
                f"{route_coordinates[node][1]}, {route_coordinates[node][0]}",
                revenues_lst[node],
            ]
            writer.writerow(data)

    print(file=file)


def draw_routes(
    map_g, route, coordinates_lst, nodes_lst, start_coord, method_used="SA"
):
    """
    Draw the route on the map
    :param map_g: the map where to draw
    :param coordinates_lst: list of coordinates tuplex x,y
    :param nodes_lst: list of nodes
    :param start_coord: index of the route coordinate to start route
    :param method_used: string to represent the method algorithm on the plot
    :return: void
    """
    # Calculate and plot routes
    import matplotlib.colors as mcolors

    DEBUG_DRAW = True
    taxicab_worked = True
    if TAXICAB:
        orig = coordinates_lst[route[0]]
        for i, item in enumerate(route[1:]):
            dest = coordinates_lst[item]
            try:
                route = taxicab.distance.shortest_path(map_g, orig, dest)
                taxicab.plot.plot_graph_route(map_g, route)
            except Exception as e:
                print(e)
                taxicab_worked = False

    if TAXICAB and taxicab_worked:
        return

    colors_nexus = mcolors.CSS4_COLORS  # ox.plot.get_colors
    colors_nexus = sorted(
        colors_nexus, key=lambda c: tuple(mcolors.rgb_to_hsv(mcolors.to_rgb(c)))
    )

    colors_nexus = list(colors_nexus)
    # print("colors_nexus", colors_nexus)

    loc_x, loc_y = start_coord
    node_start = nodes_lst[route[0]]
    fig, ax = ox.plot_graph(
        map_g, show=False, close=False, edge_color="lightgray", node_size=0
    )

    ax.scatter(
        loc_x,
        loc_y,
        c="red",
        s=100,
        alpha=0.8,
        edgecolor="k",
        marker="s",
        label=f"Start",
    )
    try:
        ax.plot(
            (loc_x, map_g.nodes[node_start]["x"]),
            (loc_y, map_g.nodes[node_start]["y"]),
            linewidth=5,
            color="red",
        )
    except Exception as e:
        print(f"node {node_start} not found")

    if len(route) <= 2:
        plt.title(f"Output route for {method_used}")
        plt.tight_layout()
        plt.show()
        return

    prev_node = node_start  # (loc_x, loc_y)
    for i, item in enumerate(route[1:]):
        current_node = nodes_lst[item]
        # print(i,item)
        ax.scatter(
            coordinates_lst[item][0],
            coordinates_lst[item][1],
            c="green",
            s=70,
            alpha=0.75,
            edgecolor="k",
            marker="o",
            label=f"Pt {i}",
        )

        color = colors_nexus[i % len(colors_nexus)]
        try:
            ax.plot(
                (coordinates_lst[item][0], map_g.nodes[current_node]["x"]),
                (coordinates_lst[item][1], map_g.nodes[current_node]["y"]),
                linewidth=3,
                color=color,
            )

        except Exception as e:
            print("Missing this node on the graph:", e)
            continue

        if DEBUG_DRAW:
            print(
                "Nodes used:",
                prev_node,
                item,
                coordinates_lst[item][0],
                coordinates_lst[item][1],
            )
        try:
            routes = nx.shortest_path(map_g, prev_node, current_node, weight="length")
            prev_node = current_node
            if DEBUG_DRAW:
                print("ok")
        except nx.NetworkXNoPath:
            print("no route between", prev_node, current_node)
            prev_node = current_node
            continue
        except Exception as e:
            print("no Routes:", e)
            continue

        if DEBUG_DRAW:
            print(routes)

        # Plot the route_lst
        ox.plot_graph_route(
            map_g,
            routes,
            ax=ax,
            route_color=color,
            route_linewidth=4,
            orig_dest_size=0,
            show=False,
            close=False,
        )
        prev_node = current_node

    routes = [prev_node]
    try:
        routes = nx.shortest_path(
            map_g, prev_node, nodes_lst[route[0]], weight="length"
        )

        if DEBUG_DRAW:
            print(routes)

        # Plot the route_lst
        ox.plot_graph_route(
            map_g,
            routes,
            ax=ax,
            route_color="red",
            route_linewidth=5,
            orig_dest_size=0,
            show=False,
            close=False,
        )

        plt.title(f"Output route for {method_used}")
        plt.tight_layout()
        plt.show()

    except Exception as e:
        print("Plot failed", e)


if __name__ == "__main__":
    FILENAME = CHECKPOINTS_LOCATIONS  # 'data_test.txt'  # Data file

    SUFFIX = "_taxicab" if TAXICAB else ""

    start_time = time.perf_counter()
    df_checkpoints = load_locations(FILENAME)
    end_time = time.perf_counter()
    total_time_work += end_time - start_time
    print("Loadin locations from file ", end_time - start_time, "sec")

    coordinates = extract_coordinates(df_checkpoints)
    if DEBUG:
        print("First and last 20 route_coordinates:")
        print(coordinates[:20])
        print(coordinates[-20:])

    VISITED = [False for _ in range(len(coordinates) * 100)]
    TESTS_LOCATIONS = [START_TEST] if isinstance(START_TEST, int) else START_TEST
    for location_index in TESTS_LOCATIONS:
        start_loc_y, start_loc_x = TEST_START[location_index]

        transport_index = INDEX_TRANSPORT
        mode = TRANSPORT_TYPES[transport_index]

        start_time = time.perf_counter()
        seprag_value = find_SEPRAG(start_loc_x, start_loc_y)
        end_time = time.perf_counter()
        total_time_work += end_time - start_time
        print("Loading SEPRAG", end_time - start_time, "sec")

        print("Distance Matrix calculation/loading")
        start_time = time.perf_counter()
        if not HAVE_DIST_MATRIX:
            if USE_SPLIT_MATRIX:
                NS = 100
                k = 0
                SN_prev = 0
                SN = NS
                while SN < len(df_checkpoints):
                    print(f"{k} distances")
                    distances = get_matrix_distances(
                        df_checkpoints[SN_prev:NS], transport_index
                    )
                    df_distances = pd.DataFrame(
                        data=distances,
                        columns=[
                            "route1",
                            "route2",
                            "distance",
                            "price",
                            "time",
                            "revenue",
                        ],
                    )
                    df_distances.to_csv(
                        f"distance_matr_{CHECKPOINTS_LOCATIONS[:-4]}_part{k}.csv",
                        index=False,
                    )
                    k += 1
                    SN_prev = SN
                    SN += NS

                if SN_prev < len(df_checkpoints):
                    print(f" last {k} distances, {SN_prev}-{len(df_checkpoints)}")
                    distances = get_matrix_distances(
                        df_checkpoints[SN_prev:], transport_index
                    )
                    df_distances = pd.DataFrame(
                        data=distances,
                        columns=[
                            "route1",
                            "route2",
                            "distance",
                            "price",
                            "time",
                            "revenue",
                        ],
                    )
                    df_distances.to_csv(
                        f"distance_matr_{CHECKPOINTS_LOCATIONS[:-4]}_part{k}.csv",
                        index=False,
                    )

                for i in range(k + 1):
                    df1 = df_checkpoints[i * NS : i * NS + NS]
                    for j in range(k + 1):
                        if i == j:
                            continue
                        df2 = df_checkpoints[j * NS : j * NS + NS]
                        print(f" pair{i} {j} distances")
                        distances = get_matrix_distances2(df1, df2, transport_index)
                        df_distances = pd.DataFrame(
                            data=distances,
                            columns=[
                                "route1",
                                "route2",
                                "distance",
                                "price",
                                "time",
                                "revenue",
                            ],
                        )
                        df_distances.to_csv(
                            f"distance_matr_{CHECKPOINTS_LOCATIONS[:-4]}_parts{i}_{j}.csv",
                            index=False,
                        )

                df_distances = get_matrix_split(CHECKPOINTS_LOCATIONS[:-4], k)
                df_distances.to_csv(
                    f"distance_matr_{CHECKPOINTS_LOCATIONS[:-4]}{SUFFIX}.csv"
                )
            else:
                distances = get_matrix_distances(df_checkpoints, transport_index)
                if DEBUG:
                    print("DISTANCE MATRIX:")
                    print(distances)

                df_distances = pd.DataFrame(
                    data=distances,
                    columns=[
                        "route1",
                        "route2",
                        "distance",
                        "price",
                        "time",
                        "revenue",
                    ],
                )
                df_distances.to_csv(
                    f"distance_matr_{CHECKPOINTS_LOCATIONS[:-4]}{SUFFIX}.csv"
                )
        else:
            df_distances = pd.read_csv(
                f"distance_matr_{CHECKPOINTS_LOCATIONS[:-4]}{SUFFIX}.csv"
            )

        end_time = time.perf_counter()
        dist_matrix_time = end_time - start_time
        if HAVE_DIST_MATRIX:
            total_time_work += dist_matrix_time
        print("Getting distance matrix takes ", end_time - start_time, "sec")

        start_time = time.perf_counter()
        G_proj = ox.project_graph(G[transport_index])
        test_node, r0 = ox.distance.nearest_nodes(
            G[transport_index], start_loc_x, start_loc_y, return_dist=True
        )
        end_time = time.perf_counter()
        total_time_work += end_time - start_time
        print("Finding Start on the map", end_time - start_time, "sec")

        if DEBUG:
            print(test_node)

        if SHOW_ALL_MAPS:
            fig, ax = ox.plot_graph(
                G[transport_index],
                show=False,
                close=False,
                edge_color="lightgray",
                node_size=0,
            )
            ax.scatter(
                start_loc_x,
                start_loc_y,
                c="red",
                s=100,
                alpha=0.8,
                edgecolor="k",
                marker="s",
                label=f"Start",
            )

        # Calculate and plot routes
        import matplotlib.colors as mcolors

        colors = mcolors.BASE_COLORS  # ox.plot.get_colors
        colors = list(colors)
        # print("colors", colors)

        print("Filtering for Cluster set")
        start_time = time.perf_counter()

        # Loop to find 10 checkpoints
        cluster_radius_current = CLUSTER_RADIUS[transport_index]
        inspector_radius_current = INSPECT_RADIUS[transport_index]

        iter_filter = 0
        while iter_filter < ITER_FILTER_MAX:
            route_lines = []
            i = 0
            cluster_set = set()
            dist_start = {}
            address_list = []
            for id2, data_row2 in df_checkpoints.iterrows():
                if seprag_value and seprag_value != data_row2["region"]:
                    continue

                longitude_x, latitude_y = (
                    data_row2["longitude"],
                    data_row2["latitude"],
                )

                dist_haver = haversine(
                    start_loc_x, start_loc_y, longitude_x, latitude_y
                )
                if dist_haver > cluster_radius_current:
                    continue

                data_node, r = ox.distance.nearest_nodes(
                    G[transport_index], longitude_x, latitude_y, return_dist=True
                )
                if DEBUG:
                    print(data_node)
                i += 1

                if SHOW_ALL_MAPS:
                    ax.scatter(
                        data_row2["longitude"],
                        data_row2["latitude"],
                        c="green",
                        s=70,
                        alpha=0.5,
                        edgecolor="k",
                        marker="o",
                        label=f"Data {id2}",
                    )
                try:
                    # distance = nx.shortest_path_length(G[transport_index], test_node, data_node, weight='length')
                    dist = dist_haver
                    taxicab_fail = True
                    if TAXICAB:
                        try:
                            route_xy = taxicab.distance.shortest_path(
                                G[transport_index],
                                (start_loc_y, start_loc_x),
                                (latitude_y, longitude_x),
                            )
                            dist = route_xy.length
                            taxicab_success = True
                        except Exception:
                            pass

                    if taxicab_fail:
                        try:
                            dist = nx.shortest_path_length(
                                G[transport_index],
                                test_node,
                                data_node,
                                weight="length",
                            )
                        except nx.NetworkXNoPath:
                            pass

                    price = dist * C[transport_index]
                    time_spent = dist / V[transport_index]
                    if DEBUG:
                        print(start_loc_x, start_loc_y, longitude_x, latitude_y)
                        print(
                            id2,
                            ":",
                            dist,
                            haversine(
                                longitude_x, latitude_y, start_loc_x, start_loc_y
                            ),
                            r,
                            r0,
                        )

                    if dist > cluster_radius_current:
                        dist = float("inf")
                        price = float("inf")
                        time_spent = float("inf")
                        VISITED[i] = True
                    else:
                        if DEBUG:
                            print("Adding note to set:")
                            print(
                                id2,
                                ":",
                                dist,
                                haversine(
                                    longitude_x, latitude_y, start_loc_x, start_loc_y
                                ),
                                r,
                                r0,
                            )

                        dist_start[id2] = [
                            dist,
                            price,
                            data_row2["name"],
                            time_spent + TI,
                            (longitude_x, latitude_y),
                            data_node,
                            data_row2["revenues"],
                        ]
                        cluster_set.add(id2)

                        if SHOW_ALL_MAPS:
                            route = nx.shortest_path(
                                G[transport_index],
                                test_node,
                                data_node,
                                weight="length",
                            )
                            if DEBUG:
                                print("shortest path:", route)
                                print(
                                    "Output locations:",
                                    (
                                        start_loc_x,
                                        G[transport_index].nodes[data_node]["x"],
                                    ),
                                    (
                                        start_loc_y,
                                        G[transport_index].nodes[data_node]["y"],
                                    ),
                                )

                            ax.plot(
                                (start_loc_x, G[transport_index].nodes[test_node]["x"]),
                                (start_loc_y, G[transport_index].nodes[test_node]["y"]),
                                linewidth=1,
                                color=colors[np.random.randint(len(colors))],
                            )

                            ax.plot(
                                (longitude_x, G[transport_index].nodes[data_node]["x"]),
                                (latitude_y, G[transport_index].nodes[data_node]["y"]),
                                linewidth=1,
                                color=colors[np.random.randint(len(colors))],
                            )
                            # Plot the route_lst
                            ox.plot_graph_route(
                                G[transport_index],
                                route,
                                ax=ax,
                                route_color=colors[np.random.randint(len(colors))],
                                route_linewidth=2,
                                orig_dest_size=0,
                                show=False,
                                close=False,
                            )

                except nx.NetworkXNoPath:
                    distance = float("inf")
                    price = float("inf")
                    time_spent = float("inf")

            if SHOW_ALL_MAPS:
                plt.title(
                    "Road Network Routes \nTest Points (Red) ↔ Data Points (Green)"
                )
                plt.tight_layout()
                plt.show()

            end_time = time.perf_counter()
            total_time_work += end_time - start_time
            print("Loop and find all Cluster points", end_time - start_time, "sec")

            print("Cluster:")
            print(cluster_set)
            print("Matrix DF:")
            print(dist_start)

            Len_Cluster = len(cluster_set)
            if Len_Cluster >= MIN_CHECKPOINTS:
                print(f"We have found {MIN_CHECKPOINTS} points")
                break

            print(f"We have not found {MIN_CHECKPOINTS} points, increase radius")
            TIME_CALCULATION_LIMIT += round_calculations
            cluster_radius_current += RADIUS_ADD
            inspector_radius_current += RADIUS_ADD
            iter_filter += 1

        c = C[transport_index]
        velocity = V[transport_index]

        # d = [v[0] for k, v in dist_start.items()]
        # w = [v[-1] for k, v in dist_start.items()]
        # if DEBUG:
        #     print("d=", d)
        #     print("w=", w)

        start_time = time.perf_counter()

        # Assign unique indices to checkpoints
        # Sort cluster IDs and create mappings
        checkpoint_ids = sorted(cluster_set)
        id_to_index = {
            id_: idx + 1 for idx, id_ in enumerate(checkpoint_ids)
        }  # +1 reserves index 0 for depot
        N = len(checkpoint_ids) + 1  # Total nodes including depot

        # Initialize matrices with np.inf (diagonal of d set to 0)
        d = np.full((N, N), np.inf)
        np.fill_diagonal(d, 0)
        # w = np.zeros((N, N))  # Default to 0.0
        # tau_matr = np.full((N, N), np.inf)

        # Fill depot connections efficiently
        for checkpoint_id, (dist_val, price_val, *_, time_val) in dist_start.items():
            i = id_to_index[checkpoint_id]
            d[0, i] = d[i, 0] = dist_val
            # w[0, i] = w[i, 0] = price_val
            # tau_matr[0, i] = tau_matr[i, 0] = time_val

        # Filter internal edges first using vectorized operations
        cluster_mask = df_distances["route1"].isin(cluster_set) & df_distances[
            "route2"
        ].isin(cluster_set)
        filtered_df = df_distances[cluster_mask]

        # Process filtered DataFrame
        for u, v, dist_val, price_val, time_val in zip(
            filtered_df["route1"].astype(int),
            filtered_df["route2"].astype(int),
            filtered_df["distance"],
            filtered_df["price"],
            filtered_df["time"],
        ):
            i, j = id_to_index[u], id_to_index[v]
            d[i, j] = dist_val
            # w[i, j] = price_val
            # tau_matr[i, j] = time_val

        # Initialize time vector
        tau = np.full(N, TI)
        tau[0] = 0

        # d = [v[0] for k, v in dist_start.items()]
        # w = [v[-1] for k, v in dist_start.items()]
        print("d=", d[:10, :10])

        # Build lists in sorted order (matches matrix indexing)
        revenues = [0] + [dist_start[cp_id][-1] for cp_id in checkpoint_ids]
        coordinates_used = [(start_loc_x, start_loc_y)] + [
            tuple(dist_start[cp_id][-3][:2]) for cp_id in checkpoint_ids
        ]
        nodes_used = [test_node] + [dist_start[cp_id][-2] for cp_id in checkpoint_ids]
        address_list = ["start"] + [dist_start[cp_id][2] for cp_id in checkpoint_ids]

        # Process street/house data
        street_hashes = [0]
        houses = [-1]
        for cp_id in checkpoint_ids:
            street, house = street_house_separate(dist_start[cp_id][2])
            street_hashes.append(hash(street))
            houses.append(house)

        end_time = time.perf_counter()
        total_time_work += end_time - start_time
        print("Filling calculation parameters: ", end_time - start_time, "sec")

        if DEBUG:
            print("Hashes")
            print(street_hashes[:5], street_hashes[-5:])
            print(houses[:5], houses[-5:])

            print("revenues", revenues)

        file_result = open(f"result_{FILENAME[:-4]}_{START_TEST}.txt", "w+")

        # # Run the algorithms
        if HEURISTIC2:
            print("Start Heuristics")
            start_time = time.perf_counter()
            result = Heuristic_search(
                N - 1,
                P,
                Tmax,
                np.array(revenues),
                c,
                np.array(d),
                tau,
                velocity,
                cluster_radius_current,
                inspector_radius_current,
                np.array(coordinates_used),
            )
            end_time = time.perf_counter()
            total_time_work += end_time - start_time
            print("Heuristics 2 time is", end_time - start_time, "sec")

            print(result)
            if SHOW_FOUND_PATH:
                draw_routes(
                    G[transport_index],
                    coordinates_used,
                    nodes_used,
                    (start_loc_x, start_loc_y),
                    method_used="Heuristics2",
                )

        text_about_street = " (street-filling)" if USE_STREET_FILL else ""

        if SIMULATED_ANNEALING:
            start_time = time.perf_counter()
            # Import and run simulated annealing
            if USE_STREET_FILL:
                print("SA", tau, d, c, velocity)
                best_route, best_score, best_revenue = (
                    solve_routing_Simulated_Annealing_streets(
                        N=N,
                        P=P,
                        Tmax=Tmax,
                        revenues=revenues,
                        cost=c,
                        dist_matr=d,
                        tau=tau,
                        v=velocity,
                        R1=cluster_radius_current,
                        r1=inspector_radius_current,
                        street_hashes=street_hashes,
                        houses=houses,
                        T_start=1000,
                        T_end=0.01,
                        alpha=0.97,
                        max_iter=500,
                    )
                )
            else:
                best_route, best_score, best_revenue = (
                    solve_routing_Simulated_Annealing(
                        N=N,
                        P=P,
                        Tmax=Tmax,
                        revenues=revenues,
                        cost=c,
                        dist_matr=d,
                        tau=tau,
                        v=velocity,
                        R1=cluster_radius_current,
                        r1=inspector_radius_current,
                        T_start=1000,
                        T_end=0.01,
                        alpha=0.97,
                        max_iter=500,
                    )
                )

            # Output
            end_time = time.perf_counter()
            total_time_work += end_time - start_time
            print("Simulated annealing time is", end_time - start_time, "sec")

            print("SA best route_lst (node indices):", best_route)
            print("Best objective value:", best_score)
            print("SA results:", best_route, best_score, file=file_result)
            print("Route", file=file_result)
            print_routes(
                best_route,
                coordinates_used,
                nodes_used,
                revenues,
                address_list,
                file=file_result,
            )

            check_routes(best_route, revenues, c, d, tau, velocity)
            if SHOW_FOUND_PATH:
                print(coordinates_used, nodes_used, (start_loc_x, start_loc_y))
                print("draw")
                draw_routes(
                    G[transport_index],
                    best_route,
                    coordinates_used,
                    nodes_used,
                    (start_loc_x, start_loc_y),
                    method_used="SA" + text_about_street,
                )
                # input()

        if GREEDY_HEURISTICS:
            start_time = time.perf_counter()
            if USE_STREET_FILL:
                best_route, t, rev_basic_heur = heuristic_routing_street(
                    N=N,
                    P=P,
                    Tmax=Tmax,
                    revenues=revenues,
                    cost=c,
                    dist_matr=d,
                    tau_lst=tau,
                    velocity=velocity,  # e.g., 60 m/min
                    R=cluster_radius_current,
                    r=inspector_radius_current,
                    street_names=street_hashes,
                    house=houses,
                )
                best_route.append(0)

            else:
                best_route, t, rev_basic_heur = heuristic_routing_street(
                    N=N,
                    P=P,
                    Tmax=Tmax,
                    revenues=revenues,
                    cost=c,
                    dist_matr=d,
                    tau_lst=tau,
                    velocity=velocity,  # e.g., 60 m/min
                    R=cluster_radius_current,
                    r=inspector_radius_current,
                )
                best_route.append(0)

            end_time = time.perf_counter()
            total_time_work += end_time - start_time
            print("Greedy heuristics time is ", end_time - start_time, "sec")

            print("Greedy: ", best_route, t, rev_basic_heur)
            print(best_route, t, rev_basic_heur, file=file_result)

            check_routes(best_route, revenues, c, d, tau, velocity)
            if SHOW_FOUND_PATH:
                draw_routes(
                    G[transport_index],
                    best_route,
                    coordinates_used,
                    nodes_used,
                    (start_loc_x, start_loc_y),
                    method_used="Basic Greedy" + text_about_street,
                )

        if BRUTEFORCE:
            print("Start Brute-Force")
            start_time = time.perf_counter()
            best_route, t, rev = brute_force_routing(
                N=N,
                P=P,
                Tmax=Tmax,
                revenues=revenues,
                cost=c,
                dist_matr=d,
                tau=tau,
                velocity=velocity,  # e.g., 60 m/min
                R=cluster_radius_current,
                r=inspector_radius_current,
            )
            best_route.append(0)

            end_time = time.perf_counter()
            total_time_work += end_time - start_time
            print("Brute-force time is ", end_time - start_time, "sec")

            print("BFS", best_route, t, rev)
            print(best_route, t, rev, file=file_result)

            check_routes(best_route, revenues, c, d, tau, velocity)
            if SHOW_FOUND_PATH:
                draw_routes(
                    G[transport_index],
                    coordinates_used,
                    nodes_used,
                    (start_loc_x, start_loc_y),
                    method_used="Brute Force",
                )

        if MILP_RUN:
            print("Start MILP")
            start_time = time.perf_counter()
            best_route, best_time, best_revenue = solve_routing_MILP(
                N=N - 1,
                P=P,
                T_max=Tmax,
                revenues=revenues,
                cost=c,
                dist_matr=d,
                tau=tau,
                v=velocity,
                R=cluster_radius_current,
                r=inspector_radius_current,
            )
            end_time = time.perf_counter()
            total_time_work += end_time - start_time
            print("MILP solution time", end_time - start_time, "sec")

            print("Chosen routes MILP:", best_route)
            print("Profit MILP:", best_revenue)

            print("Chosen routes MILP:", best_route, file=file_result)
            print("Profit MILP:", best_revenue, file=file_result)
            file_result.close()

            check_routes(best_route, revenues, c, d, tau, velocity)
            if SHOW_FOUND_PATH:
                draw_routes(
                    G[transport_index],
                    coordinates_used,
                    nodes_used,
                    (start_loc_x, start_loc_y),
                    method_used="MILP",
                )

        print("Total time of execution is ", total_time_work, "sec")
        print("Distance matrix time is", dist_matrix_time, "sec")

        if total_time_work < TIME_CALCULATION_LIMIT:
            print(
                "We managed to do calculations in time ",
                total_time_work,
                "sec, to fit ",
                TIME_CALCULATION_LIMIT,
                "sec",
            )
        else:
            print(
                "Time of calculations ",
                total_time_work,
                "sec, greater than required ",
                TIME_CALCULATION_LIMIT,
                "sec",
            )
