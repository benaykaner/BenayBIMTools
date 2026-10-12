# -*- coding: utf-8 -*-

import sys

from pyrevit import forms, revit, DB
from benay_integrity import verify_brand_integrity


__author__ = "Benay Kaner"
__copyright__ = "Copyright (c) 2026 Benay Kaner"

verify_brand_integrity()

doc = revit.doc
view = revit.active_view

DEBUG = False


def debug_print(message):
    if DEBUG:
        sys.stdout.write(
            "{}\n".format(message)
        )


TOL = 0.001
CORE_TOL = 0.005
CHAIN_REFERENCE_MIN_SPACING = DB.UnitUtils.ConvertToInternalUnits(
    5.0,
    DB.UnitTypeId.Millimeters
)

WALL_FREE_END_FACE_CACHE = {}
TERMINATING_CORE_CANDIDATE_CACHE = {}
CORE_FACE_CACHE = {}
WALL_FINISH_FACE_CACHE = {}
WALL_BBOX_CACHE = {}
COLUMN_FACE_CACHE = {}
OPENING_REFERENCE_CACHE = {}
WALL_ROOM_SIDE_VISIBILITY_CACHE = {}
OPENING_WALL_FACE_SUCCESS_IDS = set()
OPENING_WALL_FACE_MISSING_IDS = set()
OPENING_WALL_FACE_INVALID_IDS = set()
COLUMN_FACE_SUCCESS_KEYS = set()
COLUMN_FACE_INVALID_KEYS = set()
WALL_VISIBLE_GEOMETRY_USED_KEYS = set()
WALL_VISIBLE_GEOMETRY_FALLBACK_KEYS = set()
WALL_MULTI_HEIGHT_PROBE_RECOVERY_KEYS = set()
INTERMEDIATE_OPENING_SUCCESS_IDS = set()


# ============================================================
# 0. YARDIMCILAR
# ============================================================

def element_id_key(element_id):
    try:
        return element_id.IntegerValue
    except:
        return element_id.Value


def wall_info(wall):
    location = wall.Location
    if not isinstance(location, DB.LocationCurve):
        return None

    curve = location.Curve
    if not isinstance(curve, DB.Line):
        return None

    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)

    dx = abs(p1.X - p0.X)
    dy = abs(p1.Y - p0.Y)

    if dx < TOL:
        yon = "DIKEY"
    elif dy < TOL:
        yon = "YATAY"
    else:
        return None

    return {
        "curve": curve,
        "p0": p0,
        "p1": p1,
        "direction": (p1 - p0).Normalize(),
        "length": curve.Length,
        "mid_x": (p0.X + p1.X) / 2.0,
        "mid_y": (p0.Y + p1.Y) / 2.0,
        "yon": yon
    }


def wall_is_exterior(wall):
    wall_type = doc.GetElement(wall.GetTypeId())
    return wall_type.Function == DB.WallFunction.Exterior


def parse_wall_ref(wall, index):
    stable = "{}:-9999:{}".format(
        wall.Id.ToString(),
        index
    )
    return DB.Reference.ParseFromStableRepresentation(
        doc,
        stable
    )


def overlap(a_min, a_max, b_min, b_max):
    bas = max(a_min, b_min)
    bit = min(a_max, b_max)

    if bit - bas <= TOL:
        return None

    return bas, bit


def unique_values(values):
    result = []

    for value in sorted(values):
        duplicate = False

        for existing in result:
            if abs(value - existing) < 0.25:
                duplicate = True
                break

        if not duplicate:
            result.append(value)

    return result


def clean_items(items):
    items.sort(key=lambda x: x[0])
    result = []

    for coord, ref in items:
        duplicate = False

        for old_coord, old_ref in result:
            if (
                abs(coord - old_coord)
                <= CHAIN_REFERENCE_MIN_SPACING
            ):
                duplicate = True
                break

        if not duplicate:
            result.append((coord, ref))

    return result


# ============================================================
# 1. PROJE ELEMANLARINI TOPLA
# ============================================================

all_walls = DB.FilteredElementCollector(doc, view.Id)\
    .OfCategory(DB.BuiltInCategory.OST_Walls)\
    .WhereElementIsNotElementType()\
    .ToElements()

doors = DB.FilteredElementCollector(doc, view.Id)\
    .OfCategory(DB.BuiltInCategory.OST_Doors)\
    .WhereElementIsNotElementType()\
    .ToElements()

windows = DB.FilteredElementCollector(doc, view.Id)\
    .OfCategory(DB.BuiltInCategory.OST_Windows)\
    .WhereElementIsNotElementType()\
    .ToElements()

rooms_raw = DB.FilteredElementCollector(doc, view.Id)\
    .OfCategory(DB.BuiltInCategory.OST_Rooms)\
    .WhereElementIsNotElementType()\
    .ToElements()

openings = list(doors) + list(windows)

columns = []
column_ids = set()

for category_name in [
    "OST_Columns",
    "OST_StructuralColumns"
]:
    try:
        category = getattr(
            DB.BuiltInCategory,
            category_name
        )
        category_elements = DB.FilteredElementCollector(
            doc,
            view.Id
        ).OfCategory(category)\
            .WhereElementIsNotElementType()\
            .ToElements()
    except:
        category_elements = []

    for column in category_elements:
        column_id = element_id_key(column.Id)

        if column_id in column_ids:
            continue

        column_ids.add(column_id)
        columns.append(column)

rooms = []
for room in rooms_raw:
    if room.Area > 0:
        rooms.append(room)

basic_straight_walls = []
for wall in all_walls:
    if wall.WallType.Kind != DB.WallKind.Basic:
        continue

    if wall_info(wall) is None:
        continue

    basic_straight_walls.append(wall)


# ============================================================
# 2. FINISH YUZU - ROOM BOUNDARY
# ============================================================

def segment_finish_face(wall, segment_curve):
    if not isinstance(segment_curve, DB.Line):
        return None

    p0 = segment_curve.GetEndPoint(0)
    p1 = segment_curve.GetEndPoint(1)

    mid = DB.XYZ(
        (p0.X + p1.X) / 2.0,
        (p0.Y + p1.Y) / 2.0,
        (p0.Z + p1.Z) / 2.0
    )

    direction = (p1 - p0).Normalize()
    candidates = []

    for shell in [
        DB.ShellLayerType.Interior,
        DB.ShellLayerType.Exterior
    ]:
        refs = DB.HostObjectUtils.GetSideFaces(
            wall,
            shell
        )

        for ref in refs:
            face = wall.GetGeometryObjectFromReference(ref)

            if not isinstance(face, DB.PlanarFace):
                continue

            # Duvarin major finish yuzu boundary segmentine paralel olmali.
            dot = abs(
                face.FaceNormal.DotProduct(direction)
            )

            if dot > 0.05:
                continue

            distance = abs(
                (mid - face.Origin).DotProduct(face.FaceNormal)
            )

            candidates.append(
                (distance, face, ref)
            )

    if len(candidates) == 0:
        return None

    candidates.sort(key=lambda x: x[0])
    return candidates[0]


# ============================================================
# 3. DUVAR UC REFERANSLARI
# ============================================================

def wall_end_refs(wall, segment_curve):
    if not isinstance(segment_curve, DB.Line):
        return None

    p0 = segment_curve.GetEndPoint(0)
    p1 = segment_curve.GetEndPoint(1)

    direction = (p1 - p0).Normalize()
    length = segment_curve.Length

    options = DB.Options()
    options.ComputeReferences = True

    geometry = wall.get_Geometry(options)
    faces = []

    for geo in geometry:
        if not isinstance(geo, DB.Solid):
            continue

        if geo.Volume <= 0:
            continue

        for face in geo.Faces:
            if not isinstance(face, DB.PlanarFace):
                continue

            dot = abs(
                face.FaceNormal.DotProduct(direction)
            )

            if dot > 0.99 and face.Reference:
                param = (
                    face.Origin - p0
                ).DotProduct(direction)

                faces.append(
                    (param, face.Reference)
                )

    if len(faces) < 2:
        return None

    bas = min(
        faces,
        key=lambda x: abs(x[0])
    )

    bit = min(
        faces,
        key=lambda x: abs(x[0] - length)
    )

    return bas, bit


def wall_joined_ids_at_end(wall, end_index):
    location = wall.Location

    if not isinstance(location, DB.LocationCurve):
        return []

    joined_ids = []

    try:
        joined_ids = list(
            location.get_ElementsAtJoin(end_index)
        )
    except:
        try:
            joined_ids = list(
                location.ElementsAtJoin[end_index]
            )
        except:
            joined_ids = []

    wall_id = element_id_key(wall.Id)

    return [
        joined_id
        for joined_id in joined_ids
        if element_id_key(joined_id.Id) != wall_id
    ]


def cached_wall_bbox(wall):
    wall_key = element_id_key(wall.Id)

    if wall_key in WALL_BBOX_CACHE:
        return WALL_BBOX_CACHE[wall_key]

    try:
        wall_box = wall.get_BoundingBox(view)
    except:
        wall_box = None

    if wall_box is None:
        try:
            wall_box = wall.get_BoundingBox(None)
        except:
            wall_box = None

    WALL_BBOX_CACHE[wall_key] = wall_box
    return wall_box


def wall_endpoint_touching_wall(wall, endpoint):
    connection_tol = max(TOL * 5.0, 0.005)
    wall_box = cached_wall_bbox(wall)

    for other in basic_straight_walls:
        if other.Id.Equals(wall.Id):
            continue

        other_box = cached_wall_bbox(other)

        if other_box is None:
            continue

        if wall_box is not None:
            z_overlap = (
                min(wall_box.Max.Z, other_box.Max.Z)
                - max(wall_box.Min.Z, other_box.Min.Z)
            )

            if z_overlap <= TOL:
                continue

        if (
            endpoint.X >= other_box.Min.X - connection_tol
            and endpoint.X <= other_box.Max.X + connection_tol
            and endpoint.Y >= other_box.Min.Y - connection_tol
            and endpoint.Y <= other_box.Max.Y + connection_tol
        ):
            return other

    return None


def wall_joined_endpoint_confirmed(wall, endpoint, joined_ids):
    """ElementsAtJoin metadata'sini gercek geometriyle dogrular.

    ElementsAtJoin[end] dolu olmasi tek basina o ucun fiziksel olarak
    kapali oldugu anlamina gelmez (T-junction, stale join, one-sided
    join gibi durumlarda da dolu olabilir). Bu fonksiyon, join
    kaydindaki her komsu duvar icin endpoint'i o duvarin kendi
    LocationCurve'u uzerine projekte eder ve:
      - projeksiyon parametresi duvarin uzunluk araligi icinde mi
      - dik (perpendicular) mesafe toleransin altinda mi
    sorularina bakarak gercek bir fiziksel temas/kapanma olup
    olmadigini teyit eder. Sadece bu iki kosul da saglaniyorsa
    endpoint gercekten "joined/kapali" sayilir.
    """
    if len(joined_ids) == 0:
        return False

    confirm_tol = max(TOL * 5.0, 0.005)

    for joined_id in joined_ids:
        try:
            other = doc.GetElement(joined_id.Id)
        except:
            continue

        if other is None or not isinstance(other, DB.Wall):
            continue

        other_location = other.Location

        if not isinstance(other_location, DB.LocationCurve):
            continue

        other_curve = other_location.Curve

        if not isinstance(other_curve, DB.Line):
            continue

        length = other_curve.Length

        if length <= TOL:
            continue

        p0 = other_curve.GetEndPoint(0)
        p1 = other_curve.GetEndPoint(1)
        other_direction = (p1 - p0).Normalize()

        vector = endpoint - p0
        param = vector.DotProduct(other_direction)
        perpendicular = vector - other_direction.Multiply(param)
        perpendicular_distance = perpendicular.GetLength()

        if (
            param >= -confirm_tol
            and param <= length + confirm_tol
            and perpendicular_distance <= confirm_tol
        ):
            return True

    return False


def wall_bbox_contains_endpoint(wall, endpoint):
    connection_tol = max(TOL * 10.0, 0.01)
    wall_box = cached_wall_bbox(wall)

    if wall_box is None:
        return False

    return (
        endpoint.X >= wall_box.Min.X - connection_tol
        and endpoint.X <= wall_box.Max.X + connection_tol
        and endpoint.Y >= wall_box.Min.Y - connection_tol
        and endpoint.Y <= wall_box.Max.Y + connection_tol
    )


def joined_item_wall(joined_item):
    if isinstance(joined_item, DB.Wall):
        return joined_item

    try:
        element = doc.GetElement(joined_item.Id)

        if isinstance(element, DB.Wall):
            return element
    except:
        pass

    try:
        element = doc.GetElement(joined_item)

        if isinstance(element, DB.Wall):
            return element
    except:
        pass

    return None


def wall_endpoint_terminating_core_candidate(
    wall,
    end_index,
    axis
):
    cache_key = (
        element_id_key(wall.Id),
        end_index,
        axis
    )

    if cache_key in TERMINATING_CORE_CANDIDATE_CACHE:
        return TERMINATING_CORE_CANDIDATE_CACHE[
            cache_key
        ]

    info = wall_info(wall)

    if info is None:
        TERMINATING_CORE_CANDIDATE_CACHE[
            cache_key
        ] = None
        return None

    endpoint = info["curve"].GetEndPoint(end_index)
    opposite_endpoint = info["curve"].GetEndPoint(
        1 - end_index
    )

    if axis == "X":
        required_direction = "DIKEY"
        endpoint_coordinate = endpoint.X
        opposite_coordinate = opposite_endpoint.X
    else:
        required_direction = "YATAY"
        endpoint_coordinate = endpoint.Y
        opposite_coordinate = opposite_endpoint.Y

    joined_wall_ids = set()
    connected_walls = []

    for joined_item in wall_joined_ids_at_end(
        wall,
        end_index
    ):
        other = joined_item_wall(joined_item)

        if other is None:
            continue

        other_info = wall_info(other)

        if (
            other_info is None
            or other_info["yon"] != required_direction
            or not wall_bbox_contains_endpoint(
                other,
                endpoint
            )
        ):
            continue

        other_id = element_id_key(other.Id)
        joined_wall_ids.add(other_id)
        connected_walls.append(other)

    for other in basic_straight_walls:
        if other.Id.Equals(wall.Id):
            continue

        other_id = element_id_key(other.Id)

        if other_id in joined_wall_ids:
            continue

        other_info = wall_info(other)

        if (
            other_info is None
            or other_info["yon"] != required_direction
            or not wall_bbox_contains_endpoint(
                other,
                endpoint
            )
        ):
            continue

        connected_walls.append(other)

    candidates = []

    for terminating_wall in connected_walls:
        type_key = element_id_key(
            terminating_wall.WallType.Id
        )

        if type_key not in core_calibrations:
            continue

        faces = core_faces(
            terminating_wall,
            core_calibrations[type_key],
            axis
        )

        if len(faces) == 0:
            continue

        if opposite_coordinate < endpoint_coordinate - TOL:
            selected_face = min(
                faces,
                key=lambda face: face[0]
            )
        elif opposite_coordinate > endpoint_coordinate + TOL:
            selected_face = max(
                faces,
                key=lambda face: face[0]
            )
        else:
            selected_face = min(
                faces,
                key=lambda face: abs(
                    face[0] - endpoint_coordinate
                )
            )

        terminating_id = element_id_key(
            terminating_wall.Id
        )
        join_priority = (
            0
            if terminating_id in joined_wall_ids
            else 1
        )

        candidates.append(
            (
                join_priority,
                abs(
                    selected_face[0]
                    - endpoint_coordinate
                ),
                terminating_id,
                terminating_wall,
                selected_face
            )
        )

    if len(candidates) == 0:
        TERMINATING_CORE_CANDIDATE_CACHE[
            cache_key
        ] = None
        return None

    candidates.sort(
        key=lambda candidate: (
            candidate[0],
            candidate[1],
            candidate[2]
        )
    )
    selected = candidates[0]
    terminating_wall = selected[3]
    selected_face = selected[4]

    result = {
        "wall": wall,
        "wall_id": element_id_key(wall.Id),
        "end_index": end_index,
        "endpoint": endpoint,
        "coordinate": selected_face[0],
        "perpendicular_coordinate": (
            endpoint.Y
            if axis == "X"
            else endpoint.X
        ),
        "reference": selected_face[1],
        "reference_kind": "TERMINATING_CORE",
        "terminating_wall": terminating_wall,
        "terminating_wall_id": element_id_key(
            terminating_wall.Id
        )
    }

    TERMINATING_CORE_CANDIDATE_CACHE[
        cache_key
    ] = result
    return result


def wall_free_end_face_candidates(wall):
    wall_key = element_id_key(wall.Id)

    if wall_key in WALL_FREE_END_FACE_CACHE:
        return WALL_FREE_END_FACE_CACHE[wall_key]

    info = wall_info(wall)

    if info is None:
        WALL_FREE_END_FACE_CACHE[wall_key] = []
        return []

    curve = info["curve"]
    direction = info["direction"]
    endpoints = [
        curve.GetEndPoint(0),
        curve.GetEndPoint(1)
    ]
    end_face_tol = max(TOL * 5.0, 0.005)

    options = DB.Options()
    options.ComputeReferences = True

    geometry = wall.get_Geometry(options)
    end_faces = []

    for geo in geometry:
        if not isinstance(geo, DB.Solid):
            continue

        if geo.Volume <= 0:
            continue

        for face in geo.Faces:
            if not isinstance(face, DB.PlanarFace):
                continue

            ref = face.Reference

            if ref is None:
                continue

            try:
                if not ref.ElementId.Equals(wall.Id):
                    continue
            except:
                continue

            try:
                if (
                    ref.ElementReferenceType
                    != DB.ElementReferenceType.REFERENCE_TYPE_SURFACE
                ):
                    continue
            except:
                pass

            dot = abs(
                face.FaceNormal.DotProduct(direction)
            )

            if dot <= 0.99:
                continue

            end_faces.append(
                (
                    face,
                    ref
                )
            )

    result = []

    for end_index in [0, 1]:
        endpoint = endpoints[end_index]

        touching_wall = wall_endpoint_touching_wall(
            wall,
            endpoint
        )

        if touching_wall is not None:
            continue

        joined_ids = wall_joined_ids_at_end(wall, end_index)

        if len(joined_ids) > 0:
            if wall_joined_endpoint_confirmed(
                wall,
                endpoint,
                joined_ids
            ):
                continue
            # ElementsAtJoin dolu ama geometrik olarak dogrulanamadi:
            # T-junction / stale join / one-sided join false positive'i.
            # Ucu serbest aday olarak degerlendirmeye devam et.

        candidates = []

        for face, ref in end_faces:
            plane_distance = abs(
                (
                    endpoint - face.Origin
                ).DotProduct(face.FaceNormal)
            )

            if plane_distance > end_face_tol:
                continue

            try:
                area = face.Area
            except:
                area = 0.0

            candidates.append(
                (
                    plane_distance,
                    -area,
                    face,
                    ref
                )
            )

        if len(candidates) == 0:
            continue

        candidates.sort(
            key=lambda candidate: (
                candidate[0],
                candidate[1]
            )
        )
        selected = candidates[0]
        face = selected[2]
        ref = selected[3]

        if info["yon"] == "YATAY":
            coord = face.Origin.X
            perpendicular_coord = endpoint.Y
        else:
            coord = face.Origin.Y
            perpendicular_coord = endpoint.X

        result.append(
            {
                "wall": wall,
                "wall_id": element_id_key(wall.Id),
                "end_index": end_index,
                "endpoint": endpoint,
                "coordinate": coord,
                "perpendicular_coordinate": perpendicular_coord,
                "reference": ref
            }
        )

    WALL_FREE_END_FACE_CACHE[wall_key] = result
    return result


# ============================================================
# 4. KOMSU ROOM BOUNDARY DUVAR YUZU
# ============================================================

def adjacent_face_data(segment, current_start, current_direction):
    element = doc.GetElement(segment.ElementId)

    if not isinstance(element, DB.Wall):
        return None

    curve = segment.GetCurve()

    if not isinstance(curve, DB.Line):
        return None

    data = segment_finish_face(
        element,
        curve
    )

    if data is None:
        return None

    face = data[1]
    ref = data[2]

    param = (
        face.Origin - current_start
    ).DotProduct(current_direction)

    return param, ref


# ============================================================
# 5. ROOM BOUNDARY SEGMENTINDEKI OPENINGLER
# ============================================================

def segment_openings(wall, segment_curve):
    if not isinstance(segment_curve, DB.Line):
        return []

    p0 = segment_curve.GetEndPoint(0)
    p1 = segment_curve.GetEndPoint(1)

    direction = (p1 - p0).Normalize()
    length = segment_curve.Length

    found = []

    for element in openings:
        if not element.Host:
            continue

        if not element.Host.Id.Equals(wall.Id):
            continue

        if not isinstance(element.Location, DB.LocationPoint):
            continue

        param = (
            element.Location.Point - p0
        ).DotProduct(direction)

        if (
            param >= -TOL
            and param <= length + TOL
        ):
            found.append(
                (param, element)
            )

    found.sort(key=lambda x: x[0])
    return found


# ============================================================
# 6. DIMENSION CIZGISINI ROOM TARAFINA AL
# ============================================================

def room_side_dimension_line(room, segment_curve, offset):
    p0 = segment_curve.GetEndPoint(0)
    p1 = segment_curve.GetEndPoint(1)

    direction = (p1 - p0).Normalize()

    perp = DB.XYZ(
        -direction.Y,
        direction.X,
        0
    ).Normalize()

    mid = DB.XYZ(
        (p0.X + p1.X) / 2.0,
        (p0.Y + p1.Y) / 2.0,
        p0.Z
    )

    if isinstance(room.Location, DB.LocationPoint):
        room_point = room.Location.Point
        to_room = room_point - mid

        if to_room.DotProduct(perp) < 0:
            perp = perp.Negate()

    return DB.Line.CreateBound(
        p0 + perp.Multiply(offset),
        p1 + perp.Multiply(offset)
    )


ROOM_CHAIN_OFFSET = DB.UnitUtils.ConvertToInternalUnits(
    0.40,
    DB.UnitTypeId.Meters
)
ROOM_CHAIN_TRACK_TOL = 0.05
ROOM_CHAIN_SPAN_JOIN_TOL = DB.UnitUtils.ConvertToInternalUnits(
    300.0,
    DB.UnitTypeId.Millimeters
)
ROOM_SIDE_WALL_PENETRATION_TOL = DB.UnitUtils.ConvertToInternalUnits(
    10.0,
    DB.UnitTypeId.Millimeters
)
ROOM_SIDE_VISIBLE_PROBE_START = DB.UnitUtils.ConvertToInternalUnits(
    2.0,
    DB.UnitTypeId.Millimeters
)
ROOM_SIDE_VISIBLE_PROBE_DEPTH = DB.UnitUtils.ConvertToInternalUnits(
    300.0,
    DB.UnitTypeId.Millimeters
)
ROOM_SIDE_VISIBLE_PROBE_Z_INSET = DB.UnitUtils.ConvertToInternalUnits(
    50.0,
    DB.UnitTypeId.Millimeters
)


def room_chain_track(
    tracks,
    scan_coordinate,
    secondary_coordinate,
    room_id,
    span_start,
    span_end,
    boundary_end_wall_ids,
    source_wall_id,
    source_wall_is_exterior,
    source_side_sign,
    source_surface_coordinate
):
    span_min = min(span_start, span_end)
    span_max = max(span_start, span_end)

    for track in tracks:
        if (
            abs(
                track["scan_coordinate"]
                - scan_coordinate
            ) <= ROOM_CHAIN_TRACK_TOL
            and span_min
            <= track["span_end"] + ROOM_CHAIN_SPAN_JOIN_TOL
            and span_max
            >= track["span_start"] - ROOM_CHAIN_SPAN_JOIN_TOL
            and track["room_side_sign"]
            == int(source_side_sign)
        ):
            room_already_owned = room_id in track["room_ids"]

            # V13: Her Room kendi olcu adaylarini olusturur. Komsu Room
            # izleri ayni offsette durabilir ama veri olarak birlesmez.
            if not room_already_owned:
                continue

            track["span_start"] = min(
                track["span_start"],
                span_min
            )
            track["span_end"] = max(
                track["span_end"],
                span_max
            )
            track["room_ids"].add(room_id)

            track["boundary_end_wall_ids"].update(
                boundary_end_wall_ids
            )
            track["source_wall_ids"].add(
                source_wall_id
            )
            track["source_surface_coordinates"].add(
                source_surface_coordinate
            )

            if source_wall_is_exterior:
                track["exterior_source_wall_ids"].add(
                    source_wall_id
                )
            else:
                track["interior_source_wall_ids"].add(
                    source_wall_id
                )
                track["interior_source_surface_tokens"].add(
                    (
                        source_wall_id,
                        int(source_side_sign)
                    )
                )

            secondary_exists = False

            for existing_coordinate in track[
                "secondary_coordinates"
            ]:
                if (
                    abs(
                        existing_coordinate
                        - secondary_coordinate
                    ) <= ROOM_CHAIN_TRACK_TOL
                ):
                    secondary_exists = True
                    break

            if not secondary_exists:
                track["secondary_coordinates"].append(
                    secondary_coordinate
                )

            return track

    track = {
        "scan_coordinate": scan_coordinate,
        "secondary_coordinates": [
            secondary_coordinate
        ],
        "span_start": span_min,
        "span_end": span_max,
        "room_ids": set([room_id]),
        "continued_room_count": 0,
        "room_side_sign": int(source_side_sign),
        "source_surface_coordinate": source_surface_coordinate,
        "boundary_end_wall_ids": set(
            boundary_end_wall_ids
        ),
        "source_wall_ids": set([source_wall_id]),
        "source_surface_coordinates": set([
            source_surface_coordinate
        ]),
        "interior_source_wall_ids": (
            set()
            if source_wall_is_exterior
            else set([source_wall_id])
        ),
        "interior_source_surface_tokens": (
            set()
            if source_wall_is_exterior
            else set([
                (
                    source_wall_id,
                    int(source_side_sign)
                )
            ])
        ),
        "exterior_source_wall_ids": (
            set([source_wall_id])
            if source_wall_is_exterior
            else set()
        ),
        "opening_items": [],
        "opening_stables": set()
    }
    tracks.append(track)
    return track


def room_chain_jobs(tracks):
    """Yeni bilgi tasiyan uzun zincirleri once isler."""
    return sorted(
        [
            (
                track["scan_coordinate"],
                track
            )
            for track in tracks
        ],
        key=lambda item: (
            -(
                item[1]["span_end"]
                - item[1]["span_start"]
            ),
            item[0],
            item[1]["span_start"],
            item[1]["span_end"]
        )
    )


def opening_width_value(element):
    owners = [element]

    try:
        element_type = doc.GetElement(
            element.GetTypeId()
        )

        if element_type is not None:
            owners.append(element_type)
    except:
        pass

    parameter_names = [
        "DOOR_WIDTH",
        "WINDOW_WIDTH"
    ]

    for owner in owners:
        for parameter_name in parameter_names:
            try:
                built_in_parameter = getattr(
                    DB.BuiltInParameter,
                    parameter_name
                )
                parameter = owner.get_Parameter(
                    built_in_parameter
                )

                if (
                    parameter is not None
                    and parameter.StorageType
                    == DB.StorageType.Double
                ):
                    value = parameter.AsDouble()

                    if value > TOL:
                        return value
            except:
                pass

    return None


def wall_opening_face_candidates(element, axis):
    """Host duvardaki gercek bosluk yan yuzlerini bulur."""
    if not isinstance(element.Location, DB.LocationPoint):
        return []

    host = element.Host

    if not isinstance(host, DB.Wall):
        return []

    info = wall_info(host)

    if info is None:
        return []

    if (
        axis == "X"
        and info["yon"] != "YATAY"
    ):
        return []

    if (
        axis == "Y"
        and info["yon"] != "DIKEY"
    ):
        return []

    options = DB.Options()
    options.ComputeReferences = True
    options.IncludeNonVisibleObjects = True

    try:
        options.DetailLevel = DB.ViewDetailLevel.Fine
    except:
        pass

    try:
        geometry = host.get_Geometry(options)
    except:
        geometry = None

    if geometry is None:
        return []

    point = element.Location.Point
    center_coordinate = (
        point.X
        if axis == "X"
        else point.Y
    )
    width = opening_width_value(element)

    try:
        element_box = element.get_BoundingBox(view)

        if element_box is None:
            element_box = element.get_BoundingBox(None)
    except:
        element_box = None

    if width is None and element_box is not None:
        if axis == "X":
            width = element_box.Max.X - element_box.Min.X
        else:
            width = element_box.Max.Y - element_box.Min.Y

    if width is None or width <= TOL:
        return []

    search_tolerance = max(
        DB.UnitUtils.ConvertToInternalUnits(
            250.0,
            DB.UnitTypeId.Millimeters
        ),
        width * 0.35
    )
    target_low = center_coordinate - width / 2.0
    target_high = center_coordinate + width / 2.0
    candidates = []

    for geometry_object in geometry:
        if not isinstance(geometry_object, DB.Solid):
            continue

        if geometry_object.Volume <= TOL:
            continue

        for face in geometry_object.Faces:
            if not isinstance(face, DB.PlanarFace):
                continue

            reference = face.Reference

            if reference is None:
                continue

            normal = face.FaceNormal

            if abs(normal.Z) > 0.01:
                continue

            if axis == "X":
                if abs(normal.X) < 0.98:
                    continue

                coordinate = face.Origin.X
            else:
                if abs(normal.Y) < 0.98:
                    continue

                coordinate = face.Origin.Y

            distance_to_target = min(
                abs(coordinate - target_low),
                abs(coordinate - target_high)
            )

            if distance_to_target > search_tolerance:
                continue

            candidates.append(
                (
                    coordinate,
                    reference
                )
            )

    candidates = clean_items(candidates)
    low_candidates = [
        item
        for item in candidates
        if item[0] < center_coordinate - TOL
    ]
    high_candidates = [
        item
        for item in candidates
        if item[0] > center_coordinate + TOL
    ]

    if (
        len(low_candidates) == 0
        or len(high_candidates) == 0
    ):
        return []

    low_item = min(
        low_candidates,
        key=lambda item: abs(item[0] - target_low)
    )
    high_item = min(
        high_candidates,
        key=lambda item: abs(item[0] - target_high)
    )
    actual_width = high_item[0] - low_item[0]

    if (
        actual_width < width * 0.50
        or actual_width > width * 1.50
    ):
        return []

    opening_id = element_id_key(element.Id)
    host_id = element_id_key(host.Id)
    host_is_exterior = wall_is_exterior(host)
    return [
        {
            "coordinate": low_item[0],
            "reference": low_item[1],
            "element_id": opening_id,
            "host_wall_id": host_id,
            "host_is_exterior": host_is_exterior,
            "source": "WALL_OPENING_FACE"
        },
        {
            "coordinate": high_item[0],
            "reference": high_item[1],
            "element_id": opening_id,
            "host_wall_id": host_id,
            "host_is_exterior": host_is_exterior,
            "source": "WALL_OPENING_FACE"
        }
    ]


def opening_pair_is_dimensionable(element, axis, items):
    """Referans ciftini modele birakmadan gecici olcuyle sinar."""
    if len(items) != 2 or doc.IsModifiable:
        return False

    host = element.Host
    info = wall_info(host)

    if info is None:
        return False

    low_coordinate = min([item["coordinate"] for item in items])
    high_coordinate = max([item["coordinate"] for item in items])

    if high_coordinate - low_coordinate <= TOL:
        return False

    extension = DB.UnitUtils.ConvertToInternalUnits(
        100.0,
        DB.UnitTypeId.Millimeters
    )
    point = element.Location.Point
    z = info["p0"].Z

    if axis == "X":
        line = DB.Line.CreateBound(
            DB.XYZ(
                low_coordinate - extension,
                point.Y,
                z
            ),
            DB.XYZ(
                high_coordinate + extension,
                point.Y,
                z
            )
        )
    else:
        line = DB.Line.CreateBound(
            DB.XYZ(
                point.X,
                low_coordinate - extension,
                z
            ),
            DB.XYZ(
                point.X,
                high_coordinate + extension,
                z
            )
        )

    references = DB.ReferenceArray()

    for item in sorted(
        items,
        key=lambda record: record["coordinate"]
    ):
        references.Append(item["reference"])

    transaction = DB.Transaction(
        doc,
        "Benay Opening Reference Test"
    )
    valid = False

    try:
        transaction.Start()
        doc.Create.NewDimension(
            view,
            line,
            references
        )
        doc.Regenerate()
        valid = True
    except:
        valid = False
    finally:
        try:
            transaction.RollBack()
        except:
            pass

    return valid


def prepare_opening_reference_cache():
    """Tum acikliklari ana uretim transactionindan once dogrular."""
    for element in openings:
        opening_id = element_id_key(element.Id)
        host = element.Host

        if not isinstance(host, DB.Wall):
            OPENING_WALL_FACE_MISSING_IDS.add(opening_id)
            continue

        info = wall_info(host)

        if info is None:
            OPENING_WALL_FACE_MISSING_IDS.add(opening_id)
            continue

        axis = "X" if info["yon"] == "YATAY" else "Y"
        items = wall_opening_face_candidates(
            element,
            axis
        )

        if len(items) != 2:
            OPENING_WALL_FACE_MISSING_IDS.add(opening_id)
            continue

        if not opening_pair_is_dimensionable(
            element,
            axis,
            items
        ):
            OPENING_WALL_FACE_INVALID_IDS.add(opening_id)
            continue

        OPENING_REFERENCE_CACHE[(opening_id, axis)] = items
        OPENING_WALL_FACE_SUCCESS_IDS.add(opening_id)


def opening_reference_items(element, axis):
    return list(
        OPENING_REFERENCE_CACHE.get(
            (
                element_id_key(element.Id),
                axis
            ),
            []
        )
    )


def add_opening_items_to_track(
    track,
    wall,
    segment_curve,
    axis
):
    for param, element in segment_openings(
        wall,
        segment_curve
    ):
        for item in opening_reference_items(
            element,
            axis
        ):
            stable = reference_stable_text(
                item["reference"]
            )

            if stable != "<STABLE REPRESENTATION UNAVAILABLE>":
                item_key = stable
            else:
                item_key = (
                    item["element_id"],
                    round(item["coordinate"], 6)
                )

            if item_key in track["opening_stables"]:
                continue

            track["opening_stables"].add(item_key)
            track["opening_items"].append(item)


def descriptor_opening_items(
    descriptor,
    room_track,
    axis,
    boundary_min,
    boundary_max
):
    """Ayni yon ve tarama bandindaki tum uygun duvar acikliklarini toplar."""
    if axis == "X":
        required_wall_direction = "YATAY"
    else:
        required_wall_direction = "DIKEY"

    candidates = list(
        room_track.get("opening_items", [])
    )
    source_wall_ids = room_track.get(
        "source_wall_ids",
        set()
    )

    for element in openings:
        host = element.Host

        if not isinstance(host, DB.Wall):
            continue

        host_info = wall_info(host)

        if (
            host_info is None
            or host_info["yon"] != required_wall_direction
        ):
            continue

        if axis == "X":
            perpendicular_coordinate = host_info["mid_y"]
        else:
            perpendicular_coordinate = host_info["mid_x"]

        if (
            perpendicular_coordinate
            < descriptor["scan_min"] - TOL
            or perpendicular_coordinate
            > descriptor["scan_max"] + TOL
        ):
            continue

        if not coordinate_is_on_room_side(
            descriptor.get("source_surface_coordinate"),
            descriptor.get("room_side_sign", 0),
            perpendicular_coordinate
        ):
            continue

        opening_items = opening_reference_items(
            element,
            axis
        )

        if len(opening_items) != 2:
            continue

        opening_coordinates = [
            item["coordinate"]
            for item in opening_items
        ]

        if (
            max(opening_coordinates) < boundary_min - TOL
            or min(opening_coordinates) > boundary_max + TOL
        ):
            continue

        candidates.extend(opening_items)

        if element_id_key(host.Id) not in source_wall_ids:
            INTERMEDIATE_OPENING_SUCCESS_IDS.add(
                element_id_key(element.Id)
            )

    result = []
    item_keys = set()

    for item in sorted(
        candidates,
        key=lambda candidate: candidate["coordinate"]
    ):
        coordinate = item["coordinate"]

        if (
            coordinate < boundary_min - TOL
            or coordinate > boundary_max + TOL
        ):
            continue

        stable = reference_stable_text(
            item["reference"]
        )

        if stable != "<STABLE REPRESENTATION UNAVAILABLE>":
            item_key = stable
        else:
            item_key = (
                item["element_id"],
                round(coordinate, 6)
            )

        if item_key in item_keys:
            continue

        item_keys.add(item_key)
        result.append(item)

    return result


def merged_room_chain_scans(tracks, existing_scans):
    room_scan_coordinates = [
        track["scan_coordinate"]
        for track in tracks
    ]
    room_scan_coordinates.sort()
    baseline_scan_coordinates = []

    for scan_coordinate in sorted(existing_scans):
        duplicate = False

        for existing_coordinate in room_scan_coordinates:
            if (
                abs(
                    existing_coordinate
                    - scan_coordinate
                ) <= ROOM_CHAIN_TRACK_TOL
            ):
                duplicate = True
                break

        if not duplicate:
            baseline_scan_coordinates.append(
                scan_coordinate
            )

    return (
        room_scan_coordinates
        + baseline_scan_coordinates
    )


def find_room_chain_track(tracks, scan_coordinate):
    for track in tracks:
        if (
            abs(
                track["scan_coordinate"]
                - scan_coordinate
            ) <= ROOM_CHAIN_TRACK_TOL
        ):
            return track

    return None


# ============================================================
# 7. CORE KALIBRASYONU
# ============================================================

def expected_core_width(wall):
    if wall.WallType.Kind != DB.WallKind.Basic:
        return None

    compound = wall.WallType.GetCompoundStructure()

    if compound is None:
        return None

    try:
        ext = compound.GetOffsetForLocationLine(
            DB.WallLocationLine.CoreExterior
        )

        inte = compound.GetOffsetForLocationLine(
            DB.WallLocationLine.CoreInterior
        )

        return abs(ext - inte)

    except:
        return None


def measure_refs(wall, ref1, ref2):
    info = wall_info(wall)

    if info is None:
        return None

    p0 = info["p0"]
    p1 = info["p1"]

    mid = DB.XYZ(
        (p0.X + p1.X) / 2.0,
        (p0.Y + p1.Y) / 2.0,
        p0.Z
    )

    normal = wall.Orientation.Normalize()

    line = DB.Line.CreateBound(
        mid - normal.Multiply(5.0),
        mid + normal.Multiply(5.0)
    )

    refs = DB.ReferenceArray()
    refs.Append(ref1)
    refs.Append(ref2)

    transaction = DB.Transaction(
        doc,
        "Temporary Core Calibration"
    )

    try:
        transaction.Start()

        dim = doc.Create.NewDimension(
            view,
            line,
            refs
        )

        doc.Regenerate()
        value = dim.Value

        transaction.RollBack()

        if value is None:
            return None

        return abs(value)

    except:
        try:
            transaction.RollBack()
        except:
            pass

        return None


def find_core_pair(wall):
    expected = expected_core_width(wall)

    if expected is None or expected <= TOL:
        return None

    # Bu projede daha once 3-4 dogrulandi.
    try:
        ref3 = parse_wall_ref(wall, 3)
        ref4 = parse_wall_ref(wall, 4)

        value = measure_refs(
            wall,
            ref3,
            ref4
        )

        if (
            value is not None
            and abs(value - expected) <= CORE_TOL
        ):
            return (3, 4)

    except:
        pass

    # Wall Type farkliysa otomatik tara.
    best = None

    for i in range(0, 16):
        try:
            ref_i = parse_wall_ref(wall, i)
        except:
            continue

        for j in range(i + 1, 16):
            try:
                ref_j = parse_wall_ref(wall, j)
            except:
                continue

            value = measure_refs(
                wall,
                ref_i,
                ref_j
            )

            if value is None:
                continue

            difference = abs(
                value - expected
            )

            if (
                best is None
                or difference < best[0]
            ):
                best = (
                    difference,
                    i,
                    j
                )

    if best is None:
        return None

    if best[0] <= CORE_TOL:
        return (
            best[1],
            best[2]
        )

    return None


def map_core_reference_sides(wall, pair):
    try:
        ref_a = parse_wall_ref(
            wall,
            pair[0]
        )

        ref_b = parse_wall_ref(
            wall,
            pair[1]
        )
    except:
        return None

    ext_finish_refs = DB.HostObjectUtils.GetSideFaces(
        wall,
        DB.ShellLayerType.Exterior
    )

    int_finish_refs = DB.HostObjectUtils.GetSideFaces(
        wall,
        DB.ShellLayerType.Interior
    )

    if (
        ext_finish_refs.Count == 0
        or int_finish_refs.Count == 0
    ):
        return None

    ext_finish = ext_finish_refs[0]
    int_finish = int_finish_refs[0]

    a_to_ext = measure_refs(
        wall,
        ref_a,
        ext_finish
    )

    b_to_ext = measure_refs(
        wall,
        ref_b,
        ext_finish
    )

    a_to_int = measure_refs(
        wall,
        ref_a,
        int_finish
    )

    b_to_int = measure_refs(
        wall,
        ref_b,
        int_finish
    )

    if (
        a_to_ext is None
        or b_to_ext is None
        or a_to_int is None
        or b_to_int is None
    ):
        return None

    if a_to_ext <= b_to_ext:
        ext_index = pair[0]
        int_index = pair[1]
    else:
        ext_index = pair[1]
        int_index = pair[0]

    return {
        "exterior": ext_index,
        "interior": int_index
    }


def core_faces(wall, calibration, axis):
    cache_key = (
        element_id_key(wall.Id),
        axis,
        calibration["exterior"],
        calibration["interior"]
    )

    if cache_key in CORE_FACE_CACHE:
        return CORE_FACE_CACHE[cache_key]

    compound = wall.WallType.GetCompoundStructure()

    if compound is None:
        CORE_FACE_CACHE[cache_key] = []
        return []

    parameter = wall.get_Parameter(
        DB.BuiltInParameter.WALL_KEY_REF_PARAM
    )

    current_value = parameter.AsInteger()

    location_map = {
        0: DB.WallLocationLine.WallCenterline,
        1: DB.WallLocationLine.CoreCenterline,
        2: DB.WallLocationLine.FinishFaceExterior,
        3: DB.WallLocationLine.FinishFaceInterior,
        4: DB.WallLocationLine.CoreExterior,
        5: DB.WallLocationLine.CoreInterior
    }

    current_line = location_map.get(
        current_value,
        DB.WallLocationLine.WallCenterline
    )

    current_offset = compound.GetOffsetForLocationLine(
        current_line
    )

    ext_offset = compound.GetOffsetForLocationLine(
        DB.WallLocationLine.CoreExterior
    )

    int_offset = compound.GetOffsetForLocationLine(
        DB.WallLocationLine.CoreInterior
    )

    delta_ext = (
        ext_offset - current_offset
    )

    delta_int = (
        int_offset - current_offset
    )

    info = wall_info(wall)

    if info is None:
        CORE_FACE_CACHE[cache_key] = []
        return []

    p0 = info["p0"]
    p1 = info["p1"]

    mid = DB.XYZ(
        (p0.X + p1.X) / 2.0,
        (p0.Y + p1.Y) / 2.0,
        p0.Z
    )

    orientation = wall.Orientation.Normalize()

    ext_point = (
        mid
        + orientation.Multiply(delta_ext)
    )

    int_point = (
        mid
        + orientation.Multiply(delta_int)
    )

    try:
        ext_ref = parse_wall_ref(
            wall,
            calibration["exterior"]
        )

        int_ref = parse_wall_ref(
            wall,
            calibration["interior"]
        )
    except:
        CORE_FACE_CACHE[cache_key] = []
        return []

    if axis == "X":
        ext_coord = ext_point.X
        int_coord = int_point.X
    else:
        ext_coord = ext_point.Y
        int_coord = int_point.Y

    result = [
        (
            ext_coord,
            ext_ref
        ),
        (
            int_coord,
            int_ref
        )
    ]

    result.sort(
        key=lambda x: x[0]
    )

    CORE_FACE_CACHE[cache_key] = result
    return result


def column_plan_faces(column, axis):
    """Kolonun olcu yonune dik, referanslanabilir plan yuzlerini toplar."""
    cache_key = (
        element_id_key(column.Id),
        axis
    )

    if cache_key in COLUMN_FACE_CACHE:
        return COLUMN_FACE_CACHE[cache_key]

    options = DB.Options()
    options.ComputeReferences = True
    options.IncludeNonVisibleObjects = True

    try:
        geometry = column.get_Geometry(options)
    except:
        geometry = None

    face_records = []

    if geometry is not None:
        geometry_records = []

        for geo in geometry:
            if isinstance(geo, DB.Solid):
                geometry_records.append(
                    (
                        geo,
                        DB.Transform.Identity
                    )
                )
            elif isinstance(geo, DB.GeometryInstance):
                try:
                    symbol_geometry = geo.GetSymbolGeometry()
                    transform = geo.Transform
                except:
                    symbol_geometry = None
                    transform = None

                if symbol_geometry is None or transform is None:
                    continue

                for symbol_geo in symbol_geometry:
                    if isinstance(symbol_geo, DB.Solid):
                        geometry_records.append(
                            (
                                symbol_geo,
                                transform
                            )
                        )

        for solid, transform in geometry_records:
            if solid.Volume <= TOL:
                continue

            for face in solid.Faces:
                if not isinstance(face, DB.PlanarFace):
                    continue

                ref = face.Reference

                if ref is None:
                    continue

                try:
                    normal = transform.OfVector(
                        face.FaceNormal
                    ).Normalize()
                    origin = transform.OfPoint(face.Origin)
                except:
                    normal = face.FaceNormal
                    origin = face.Origin

                if abs(normal.Z) > 0.01:
                    continue

                if axis == "X":
                    if abs(normal.X) < 0.98:
                        continue

                    coordinate = origin.X
                else:
                    if abs(normal.Y) < 0.98:
                        continue

                    coordinate = origin.Y

                face_records.append(
                    (
                        coordinate,
                        ref
                    )
                )

    face_records = clean_items(face_records)
    COLUMN_FACE_CACHE[cache_key] = face_records
    return face_records


def column_faces_are_dimensionable(
    column,
    axis,
    face_records
):
    """Kolon yuzlerini modele birakmadan gecici olcuyle sinar."""
    if len(face_records) < 2 or doc.IsModifiable:
        return False

    try:
        box = column.get_BoundingBox(view)

        if box is None:
            box = column.get_BoundingBox(None)
    except:
        box = None

    if box is None:
        return False

    low_coordinate = face_records[0][0]
    high_coordinate = face_records[-1][0]

    if high_coordinate - low_coordinate <= TOL:
        return False

    extension = DB.UnitUtils.ConvertToInternalUnits(
        100.0,
        DB.UnitTypeId.Millimeters
    )
    center_x = (box.Min.X + box.Max.X) / 2.0
    center_y = (box.Min.Y + box.Max.Y) / 2.0
    try:
        z = view.GenLevel.Elevation
    except:
        z = box.Min.Z

    if axis == "X":
        line = DB.Line.CreateBound(
            DB.XYZ(
                low_coordinate - extension,
                center_y,
                z
            ),
            DB.XYZ(
                high_coordinate + extension,
                center_y,
                z
            )
        )
    else:
        line = DB.Line.CreateBound(
            DB.XYZ(
                center_x,
                low_coordinate - extension,
                z
            ),
            DB.XYZ(
                center_x,
                high_coordinate + extension,
                z
            )
        )

    references = DB.ReferenceArray()

    for coordinate, reference in face_records:
        references.Append(reference)

    transaction = DB.Transaction(
        doc,
        "Benay Column Reference Test"
    )
    valid = False

    try:
        transaction.Start()
        doc.Create.NewDimension(
            view,
            line,
            references
        )
        doc.Regenerate()
        valid = True
    except:
        valid = False
    finally:
        try:
            transaction.RollBack()
        except:
            pass

    return valid


def prepare_column_face_cache():
    """Kolon referanslarini ana uretimden once dogrular."""
    for column in columns:
        column_id = element_id_key(column.Id)

        for axis in ["X", "Y"]:
            cache_key = (
                column_id,
                axis
            )
            face_records = column_plan_faces(
                column,
                axis
            )

            if len(face_records) < 2:
                continue

            if column_faces_are_dimensionable(
                column,
                axis,
                face_records
            ):
                COLUMN_FACE_SUCCESS_KEYS.add(cache_key)
            else:
                COLUMN_FACE_INVALID_KEYS.add(cache_key)
                COLUMN_FACE_CACHE[cache_key] = []


def column_items_for_chain(
    axis,
    scan_coordinate,
    boundary_min,
    boundary_max
):
    result = []

    for column in columns:
        try:
            box = column.get_BoundingBox(view)

            if box is None:
                box = column.get_BoundingBox(None)
        except:
            box = None

        if box is None:
            continue

        if axis == "X":
            crosses_scan = (
                scan_coordinate >= box.Min.Y - TOL
                and scan_coordinate <= box.Max.Y + TOL
            )
        else:
            crosses_scan = (
                scan_coordinate >= box.Min.X - TOL
                and scan_coordinate <= box.Max.X + TOL
            )

        if not crosses_scan:
            continue

        column_id = element_id_key(column.Id)

        for coordinate, ref in column_plan_faces(
            column,
            axis
        ):
            if (
                coordinate < boundary_min - TOL
                or coordinate > boundary_max + TOL
            ):
                continue

            result.append(
                (
                    coordinate,
                    ref,
                    column_id
                )
            )

    result.sort(key=lambda item: item[0])
    return result


def column_items_for_room_track(
    axis,
    room_track,
    boundary_min,
    boundary_max
):
    """Offset hatti ile gercek Room duvar sinirindaki kolonlari birlestirir."""
    scan_coordinates = [
        room_track["scan_coordinate"]
    ]
    scan_coordinates.extend(
        list(
            room_track.get(
                "source_surface_coordinates",
                set()
            )
        )
    )
    result = []

    for scan_coordinate in scan_coordinates:
        for item in column_items_for_chain(
            axis,
            scan_coordinate,
            boundary_min,
            boundary_max
        ):
            duplicate = False

            for existing in result:
                if (
                    abs(existing[0] - item[0]) < TOL
                    and existing[2] == item[2]
                ):
                    duplicate = True
                    break

            if not duplicate:
                result.append(item)

    result.sort(key=lambda item: item[0])
    return result


# ============================================================
# 8. HER WALL TYPE ICIN CORE CALIBRATION
# ============================================================

type_samples = {}

for wall in basic_straight_walls:
    key = element_id_key(
        wall.WallType.Id
    )

    if key not in type_samples:
        type_samples[key] = wall


core_calibrations = {}

for key in type_samples:
    sample_wall = type_samples[key]

    pair = find_core_pair(
        sample_wall
    )

    if pair is None:
        continue

    sides = map_core_reference_sides(
        sample_wall,
        pair
    )

    if sides is None:
        continue

    core_calibrations[key] = sides


# ============================================================
# 9. CORE SCAN HATLARI
# ============================================================

scan_x = []
scan_y = []

for room in rooms:
    if not isinstance(
        room.Location,
        DB.LocationPoint
    ):
        continue

    point = room.Location.Point

    scan_x.append(point.X)
    scan_y.append(point.Y)


scan_x = unique_values(scan_x)
scan_y = unique_values(scan_y)


def crosses_y(wall, y):
    info = wall_info(wall)

    p0 = info["p0"]
    p1 = info["p1"]

    return (
        min(p0.Y, p1.Y) - TOL
        <= y
        <= max(p0.Y, p1.Y) + TOL
    )


def crosses_x(wall, x):
    info = wall_info(wall)

    p0 = info["p0"]
    p1 = info["p1"]

    return (
        min(p0.X, p1.X) - TOL
        <= x
        <= max(p0.X, p1.X) + TOL
    )


def interval_penetrates_room_side(
    interval_min,
    interval_max,
    scan_coordinate,
    room_side_sign
):
    """Duvar ekseninin tarama yuzunu gecip Room tarafina girdigini sinar."""
    if room_side_sign == 0:
        return True

    if room_side_sign > 0:
        return (
            interval_max
            > scan_coordinate + ROOM_SIDE_WALL_PENETRATION_TOL
        )

    return (
        interval_min
        < scan_coordinate - ROOM_SIDE_WALL_PENETRATION_TOL
    )


def geometry_solids(geometry):
    result = []

    if geometry is None:
        return result

    for geometry_object in geometry:
        if isinstance(geometry_object, DB.Solid):
            try:
                if geometry_object.Volume > TOL:
                    result.append(geometry_object)
            except:
                pass
            continue

        if not isinstance(geometry_object, DB.GeometryInstance):
            continue

        try:
            instance_geometry = geometry_object.GetInstanceGeometry()
        except:
            instance_geometry = None

        if instance_geometry is None:
            continue

        for instance_object in instance_geometry:
            if not isinstance(instance_object, DB.Solid):
                continue

            try:
                if instance_object.Volume > TOL:
                    result.append(instance_object)
            except:
                pass

    return result


def probe_elevation_values(minimum_z, maximum_z):
    height = maximum_z - minimum_z

    if height <= TOL:
        return [
            (minimum_z + maximum_z) / 2.0
        ]

    inset = min(
        ROOM_SIDE_VISIBLE_PROBE_Z_INSET,
        height / 4.0
    )
    candidates = [
        minimum_z + inset,
        (minimum_z + maximum_z) / 2.0,
        maximum_z - inset
    ]
    result = []

    for candidate in candidates:
        if all([
            abs(candidate - existing) > TOL
            for existing in result
        ]):
            result.append(candidate)

    return result


def wall_room_side_probe_lines(
    wall,
    wall_direction,
    scan_coordinate,
    room_side_sign
):
    info = wall_info(wall)

    if info is None or room_side_sign == 0:
        return []

    try:
        wall_box = wall.get_BoundingBox(None)
    except:
        wall_box = None

    if wall_box is None:
        wall_box = cached_wall_bbox(wall)

    if wall_box is not None:
        elevations = probe_elevation_values(
            wall_box.Min.Z,
            wall_box.Max.Z
        )
    else:
        elevations = [
            info["p0"].Z + DB.UnitUtils.ConvertToInternalUnits(
                1.0,
                DB.UnitTypeId.Meters
            )
        ]

    near_coordinate = (
        scan_coordinate
        + room_side_sign * ROOM_SIDE_VISIBLE_PROBE_START
    )
    far_coordinate = (
        scan_coordinate
        + room_side_sign * ROOM_SIDE_VISIBLE_PROBE_DEPTH
    )

    result = []

    for z in elevations:
        if wall_direction == "DIKEY":
            start = DB.XYZ(
                info["mid_x"],
                near_coordinate,
                z
            )
            end = DB.XYZ(
                info["mid_x"],
                far_coordinate,
                z
            )
        else:
            start = DB.XYZ(
                near_coordinate,
                info["mid_y"],
                z
            )
            end = DB.XYZ(
                far_coordinate,
                info["mid_y"],
                z
            )

        try:
            result.append(
                DB.Line.CreateBound(start, end)
            )
        except:
            pass

    return result


def wall_visible_geometry_penetrates_room_side(
    wall,
    wall_direction,
    scan_coordinate,
    room_side_sign
):
    cache_key = (
        element_id_key(wall.Id),
        wall_direction,
        round(scan_coordinate, 6),
        int(room_side_sign)
    )

    if cache_key in WALL_ROOM_SIDE_VISIBILITY_CACHE:
        return WALL_ROOM_SIDE_VISIBILITY_CACHE[cache_key]

    probe_lines = wall_room_side_probe_lines(
        wall,
        wall_direction,
        scan_coordinate,
        room_side_sign
    )

    if len(probe_lines) == 0:
        WALL_ROOM_SIDE_VISIBILITY_CACHE[cache_key] = None
        return None

    for use_active_view in [True, False]:
        options = DB.Options()
        options.ComputeReferences = False
        options.IncludeNonVisibleObjects = False

        if use_active_view:
            try:
                options.View = view
            except:
                continue

        try:
            geometry = wall.get_Geometry(options)
        except:
            geometry = None

        solids = geometry_solids(geometry)

        if len(solids) == 0:
            continue

        intersection_options = DB.SolidCurveIntersectionOptions()
        intersects = False
        successful_probe_index = None

        try:
            for probe_index, probe_line in enumerate(probe_lines):
                for solid in solids:
                    intersection = None

                    try:
                        intersection = solid.IntersectWithCurve(
                            probe_line,
                            intersection_options
                        )
                        if intersection.SegmentCount > 0:
                            intersects = True
                            successful_probe_index = probe_index
                            break
                    except:
                        pass
                    finally:
                        if intersection is not None:
                            try:
                                intersection.Dispose()
                            except:
                                pass

                if intersects:
                    break
        finally:
            try:
                intersection_options.Dispose()
            except:
                pass

        WALL_VISIBLE_GEOMETRY_USED_KEYS.add(cache_key)

        if (
            intersects
            and successful_probe_index is not None
            and successful_probe_index > 0
        ):
            WALL_MULTI_HEIGHT_PROBE_RECOVERY_KEYS.add(
                cache_key
            )

        WALL_ROOM_SIDE_VISIBILITY_CACHE[cache_key] = intersects
        return intersects

    WALL_ROOM_SIDE_VISIBILITY_CACHE[cache_key] = None
    return None


def wall_penetrates_room_side(
    wall,
    wall_direction,
    scan_coordinate,
    room_side_sign
):
    geometry_result = wall_visible_geometry_penetrates_room_side(
        wall,
        wall_direction,
        scan_coordinate,
        room_side_sign
    )

    if geometry_result is not None:
        return geometry_result

    fallback_key = (
        element_id_key(wall.Id),
        wall_direction,
        round(scan_coordinate, 6),
        int(room_side_sign)
    )
    WALL_VISIBLE_GEOMETRY_FALLBACK_KEYS.add(fallback_key)
    info = wall_info(wall)

    if wall_direction == "DIKEY":
        interval_min = min(info["p0"].Y, info["p1"].Y)
        interval_max = max(info["p0"].Y, info["p1"].Y)
    else:
        interval_min = min(info["p0"].X, info["p1"].X)
        interval_max = max(info["p0"].X, info["p1"].X)

    return interval_penetrates_room_side(
        interval_min,
        interval_max,
        scan_coordinate,
        room_side_sign
    )


# ============================================================
# 10. V6 EK YARDIMCILAR
# ============================================================


def wall_finish_faces(wall, axis):
    """Duvarin iki major finish yuzunu coordinate + Reference olarak verir."""
    cache_key = (
        element_id_key(wall.Id),
        axis
    )

    if cache_key in WALL_FINISH_FACE_CACHE:
        return WALL_FINISH_FACE_CACHE[cache_key]

    result = []

    try:
        exterior_refs = list(
            DB.HostObjectUtils.GetSideFaces(
                wall,
                DB.ShellLayerType.Exterior
            )
        )
    except:
        exterior_refs = []

    try:
        interior_refs = list(
            DB.HostObjectUtils.GetSideFaces(
                wall,
                DB.ShellLayerType.Interior
            )
        )
    except:
        interior_refs = []

    info = wall_info(wall)
    orientation = wall.Orientation.Normalize()

    def fallback_coord(shell):
        p0 = info["p0"]
        p1 = info["p1"]

        mid = DB.XYZ(
            (p0.X + p1.X) / 2.0,
            (p0.Y + p1.Y) / 2.0,
            p0.Z
        )

        point = None

        try:
            compound = wall.WallType.GetCompoundStructure()
            parameter = wall.get_Parameter(
                DB.BuiltInParameter.WALL_KEY_REF_PARAM
            )

            location_map = {
                0: DB.WallLocationLine.WallCenterline,
                1: DB.WallLocationLine.CoreCenterline,
                2: DB.WallLocationLine.FinishFaceExterior,
                3: DB.WallLocationLine.FinishFaceInterior,
                4: DB.WallLocationLine.CoreExterior,
                5: DB.WallLocationLine.CoreInterior
            }

            current_line = location_map.get(
                parameter.AsInteger(),
                DB.WallLocationLine.WallCenterline
            )

            if shell == DB.ShellLayerType.Exterior:
                finish_line = DB.WallLocationLine.FinishFaceExterior
            else:
                finish_line = DB.WallLocationLine.FinishFaceInterior

            current_offset = compound.GetOffsetForLocationLine(
                current_line
            )
            finish_offset = compound.GetOffsetForLocationLine(
                finish_line
            )

            point = mid + orientation.Multiply(
                finish_offset - current_offset
            )

        except:
            half_width = wall.Width / 2.0

            if shell == DB.ShellLayerType.Exterior:
                point = mid + orientation.Multiply(half_width)
            else:
                point = mid - orientation.Multiply(half_width)

        if axis == "X":
            return point.X

        return point.Y

    for shell, refs in [
        (DB.ShellLayerType.Interior, interior_refs),
        (DB.ShellLayerType.Exterior, exterior_refs)
    ]:

        for ref in refs:
            try:
                face = wall.GetGeometryObjectFromReference(ref)
            except:
                face = None

            if isinstance(face, DB.PlanarFace):
                if axis == "X":
                    coord = face.Origin.X
                else:
                    coord = face.Origin.Y
            else:
                coord = fallback_coord(shell)

            result.append(
                (
                    coord,
                    ref
                )
            )

    result.sort(key=lambda x: x[0])

    debug_print(
        "Wall ID: {} | Flipped: {} | Exterior ref count: {} | "
        "Interior ref count: {} | Added finish ref count: {}".format(
            wall.Id.ToString(),
            wall.Flipped,
            len(exterior_refs),
            len(interior_refs),
            len(result)
        )
    )

    WALL_FINISH_FACE_CACHE[cache_key] = result
    return result


def wall_segment_key(wall, curve):
    """Ayni Room boundary duvar segmentinin iki kez olculenmesini engeller."""
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)

    a = (
        round(p0.X, 4),
        round(p0.Y, 4),
        round(p0.Z, 4)
    )

    b = (
        round(p1.X, 4),
        round(p1.Y, 4),
        round(p1.Z, 4)
    )

    if b < a:
        a, b = b, a

    return (
        element_id_key(wall.Id),
        a,
        b
    )


def chain_signature(items):
    """Ayni geometrik zincirin farkli Room noktalarinda tekrar uretilmesini engeller."""
    return tuple([
        round(item[0], 4)
        for item in items
    ])


def chain_is_near_visual_duplicate(
    registry,
    items,
    line_coordinate
):
    visual_signature = chain_signature(items)
    existing_coordinates = registry.get(
        visual_signature,
        []
    )
    duplicate_distance = (
        ROOM_CHAIN_OFFSET
        + ROOM_CHAIN_TRACK_TOL
    )

    for existing_coordinate in existing_coordinates:
        if (
            abs(
                existing_coordinate
                - line_coordinate
            ) <= duplicate_distance
        ):
            return True

    return False


def register_chain_visual_signature(
    registry,
    items,
    line_coordinate
):
    visual_signature = chain_signature(items)

    if visual_signature not in registry:
        registry[visual_signature] = []

    registry[visual_signature].append(
        line_coordinate
    )


def room_topology_chain_key(
    descriptor,
    items,
    variant
):
    """Ayni mahalde ayni referans zincirini ikinci kez olusturma."""
    room_ids = tuple(descriptor.get("room_ids", tuple()))

    if len(room_ids) == 0:
        return None

    return (
        descriptor["direction"],
        room_ids,
        variant,
        chain_reference_content_signature(items)
    )


def chain_geometry_coordinates(items):
    """Zincirin ekranda anlattigi fiziksel kirilma koordinatlari."""
    return frozenset([
        round(item[0], 4)
        for item in items
    ])


def chain_geometry_is_covered(
    registry,
    items,
    chain_kind
):
    """Aday zincir daha onceki zincire yeni geometrik bilgi ekliyor mu?"""
    candidate_coordinates = chain_geometry_coordinates(items)

    if len(candidate_coordinates) < 2:
        return True

    for record in registry:
        if record["chain_kind"] != chain_kind:
            continue

        if candidate_coordinates.issubset(
            record["coordinates"]
        ):
            return True

    return False


def register_chain_geometry_coverage(
    registry,
    items,
    chain_kind
):
    registry.append(
        {
            "chain_kind": chain_kind,
            "coordinates": chain_geometry_coordinates(items)
        }
    )


def smart_chain_candidate_profiles(
    wall_direction,
    scan_coordinate,
    room_track
):
    """Olcu olusturmadan once bir Room izinin aday zincirlerini kurar."""
    chain = full_finish_chain(
        wall_direction,
        scan_coordinate,
        room_track
    )

    if chain is None:
        return []

    descriptor = chain["descriptor"]
    axis = descriptor["direction"]
    core_items = []

    for wall in descriptor["walls"]:
        wall_type_key = element_id_key(
            wall.WallType.Id
        )

        if wall_type_key not in core_calibrations:
            continue

        core_items.extend(
            core_faces(
                wall,
                core_calibrations[wall_type_key],
                axis
            )
        )

    for candidate in descriptor[
        "accepted_finish_endpoint_candidates"
    ]:
        core_items.append(
            (
                candidate["coordinate"],
                candidate["reference"]
            )
        )

    if axis == "X":
        first_boundary_coordinate = wall_info(
            descriptor["first_exterior_boundary"]
        )["mid_x"]
        last_boundary_coordinate = wall_info(
            descriptor["last_exterior_boundary"]
        )["mid_x"]
    else:
        first_boundary_coordinate = wall_info(
            descriptor["first_exterior_boundary"]
        )["mid_y"]
        last_boundary_coordinate = wall_info(
            descriptor["last_exterior_boundary"]
        )["mid_y"]

    boundary_min = min(
        first_boundary_coordinate,
        last_boundary_coordinate
    )
    boundary_max = max(
        first_boundary_coordinate,
        last_boundary_coordinate
    )

    for coordinate, reference, column_id in column_items_for_room_track(
        axis,
        room_track,
        boundary_min,
        boundary_max
    ):
        core_items.append(
            (
                coordinate,
                reference
            )
        )

    core_only_items = clean_items(
        list(core_items)
    )
    opening_reference_count = 0

    for opening_item in room_track["opening_items"]:
        coordinate = opening_item["coordinate"]

        if (
            coordinate < boundary_min - TOL
            or coordinate > boundary_max + TOL
        ):
            continue

        core_items.append(
            (
                coordinate,
                opening_item["reference"]
            )
        )
        opening_reference_count += 1

    detailed_items = clean_items(core_items)
    profiles = []

    def append_profile(items, variant, chain_kind):
        if len(items) < 2:
            return

        coordinates = chain_geometry_coordinates(items)
        sorted_coordinates = sorted(coordinates)
        room_ids = frozenset(
            descriptor.get(
                "room_ids",
                tuple()
            )
        )
        interior_source_surface_tokens = frozenset(
            room_track.get(
                "interior_source_surface_tokens",
                set()
            )
        )
        interior_surface_keys = frozenset([
            (
                room_id,
                surface_token[0],
                surface_token[1]
            )
            for room_id in room_ids
            for surface_token in interior_source_surface_tokens
        ])

        profiles.append(
            {
                "axis": axis,
                "track_token": id(room_track),
                "variant": variant,
                "chain_kind": chain_kind,
                "room_ids": room_ids,
                "force_interior_surface": (
                    len(interior_surface_keys) > 0
                ),
                "interior_surface_keys": interior_surface_keys,
                "coordinates": coordinates,
                "interval_start": sorted_coordinates[0],
                "interval_end": sorted_coordinates[-1],
                "interval_length": (
                    sorted_coordinates[-1]
                    - sorted_coordinates[0]
                ),
                "richness": len(coordinates),
                "scan_coordinate": scan_coordinate
            }
        )

    if opening_reference_count > 0:
        append_profile(
            detailed_items,
            "MAIN",
            "DETAIL"
        )
        append_profile(
            core_only_items,
            "SECONDARY",
            "TOTAL"
        )
    else:
        append_profile(
            detailed_items,
            "MAIN",
            "TOTAL"
        )

    return profiles


def smart_candidate_repeats(owner, candidate):
    """Aday yeni zincir bilgisi vermiyorsa onceki kazanan tarafindan kapsanir."""
    if owner["axis"] != candidate["axis"]:
        return False

    if owner["chain_kind"] != candidate["chain_kind"]:
        return False

    if len(
        owner["room_ids"].intersection(
            candidate["room_ids"]
        )
    ) == 0:
        return False

    if candidate["force_interior_surface"]:
        if not owner["force_interior_surface"]:
            return False

        if len(
            owner["interior_surface_keys"].intersection(
                candidate["interior_surface_keys"]
            )
        ) == 0:
            return False

    interval_tolerance = ROOM_CHAIN_TRACK_TOL
    same_interval = (
        abs(
            owner["interval_start"]
            - candidate["interval_start"]
        ) <= interval_tolerance
        and abs(
            owner["interval_end"]
            - candidate["interval_end"]
        ) <= interval_tolerance
    )

    if owner["chain_kind"] == "TOTAL" and same_interval:
        return True

    if (
        owner["chain_kind"] == "DETAIL"
        and same_interval
        and owner["coordinates"] == candidate["coordinates"]
    ):
        return True

    candidate_inside_owner = (
        candidate["interval_start"]
        >= owner["interval_start"] - interval_tolerance
        and candidate["interval_end"]
        <= owner["interval_end"] + interval_tolerance
    )

    if (
        candidate_inside_owner
        and candidate["coordinates"].issubset(
            owner["coordinates"]
        )
    ):
        return True

    return False


def select_smart_chain_candidates(profiles):
    """Uzun ve bilgi bakimindan zengin adaylari secip tekrarlarini eler."""
    ordered_profiles = sorted(
        profiles,
        key=lambda profile: (
            -(
                1
                if profile["force_interior_surface"]
                else 0
            ),
            -profile["interval_length"],
            profile["scan_coordinate"],
            -profile["richness"],
            -(
                1
                if profile["variant"] == "SECONDARY"
                else 0
            )
        )
    )
    selected = []
    rejected_count = 0

    for candidate in ordered_profiles:
        repeated = False

        for owner in selected:
            if smart_candidate_repeats(owner, candidate):
                repeated = True
                break

        if repeated:
            rejected_count += 1
            continue

        selected.append(candidate)

    allowed = set([
        (
            profile["track_token"],
            profile["variant"]
        )
        for profile in selected
    ])
    return allowed, rejected_count


def first_secondary_coordinate(room_track):
    """Her Room yuzeyi icin yalnizca tek ve duzenli ikinci hat kullan."""
    coordinates = room_track.get(
        "secondary_coordinates",
        []
    )

    if len(coordinates) == 0:
        return None

    scan_coordinate = room_track["scan_coordinate"]
    return sorted(
        coordinates,
        key=lambda coordinate: abs(
            coordinate - scan_coordinate
        )
    )[0]


def reference_stable_text(ref):
    try:
        return ref.ConvertToStableRepresentation(doc)
    except:
        return "<STABLE REPRESENTATION UNAVAILABLE>"


def chain_reference_content_signature(items):
    signature = []

    for coordinate, reference in items:
        stable = reference_stable_text(reference)

        if stable != "<STABLE REPRESENTATION UNAVAILABLE>":
            signature.append(stable)
            continue

        try:
            element_key = element_id_key(
                reference.ElementId
            )
        except:
            element_key = "UNKNOWN"

        signature.append(
            "{}@{:.6f}".format(
                element_key,
                coordinate
            )
        )

    return tuple(signature)


def log_clean_items_diagnostic(
    chain_type,
    descriptor,
    raw_records,
    cleaned_items
):
    if not DEBUG:
        return

    ordered_records = sorted(
        raw_records,
        key=lambda record: record[0]
    )
    kept_records = []
    removed_records = []

    for record in ordered_records:
        coord = record[0]
        merged_with = None

        for existing in kept_records:
            if abs(coord - existing[0]) < TOL:
                merged_with = existing
                break

        if merged_with is None:
            kept_records.append(record)
        else:
            removed_records.append(
                (
                    record,
                    merged_with
                )
            )

    wall_ids = descriptor["wall_ids"]
    expected_count = len(wall_ids) * 2

    if chain_type == "Finish":
        expected_count += len(
            descriptor.get(
                "accepted_finish_endpoint_candidates",
                []
            )
        )

    expected_count += descriptor.get(
        "room_opening_reference_count",
        0
    )

    debug_print("=== CLEAN_ITEMS REFERENCE DIAGNOSTIC ===")
    debug_print("Chain type: {}".format(chain_type))
    debug_print("Direction: {}".format(descriptor["direction"]))
    debug_print(
        "Scan coordinate: {:.6f}".format(
            descriptor["scan_coordinate"]
        )
    )
    debug_print(
        "Descriptor Wall IDs: {}".format(
            ", ".join([
                str(wall_id)
                for wall_id in wall_ids
            ])
        )
    )
    debug_print(
        "Expected reference count: {}".format(
            expected_count
        )
    )
    debug_print(
        "Reference count before clean_items: {}".format(
            len(raw_records)
        )
    )
    debug_print(
        "Reference count after clean_items: {}".format(
            len(cleaned_items)
        )
    )

    if len(removed_records) == 0:
        debug_print("Removed references: NONE")

    for removed, existing in removed_records:
        removed_coord = removed[0]
        removed_ref = removed[1]
        removed_wall_id = removed[2]
        existing_coord = existing[0]
        existing_ref = existing[1]
        existing_wall_id = existing[2]
        removed_stable = reference_stable_text(removed_ref)
        existing_stable = reference_stable_text(existing_ref)

        debug_print(
            "REMOVED REFERENCE | Wall ID: {} | Coordinate: {:.9f} | "
            "Stable representation: {}".format(
                removed_wall_id,
                removed_coord,
                removed_stable
            )
        )
        debug_print(
            "MERGED WITH EXISTING REFERENCE | Wall ID: {} | "
            "Coordinate: {:.9f} | Stable representation: {} | "
            "Coordinate delta: {:.9f}".format(
                existing_wall_id,
                existing_coord,
                existing_stable,
                abs(removed_coord - existing_coord)
            )
        )

        stable_unavailable = (
            "<STABLE REPRESENTATION UNAVAILABLE>"
        )

        if (
            (
                removed_stable != stable_unavailable
                or existing_stable != stable_unavailable
            )
            and removed_stable != existing_stable
        ):
            debug_print("DISTINCT REFERENCES MERGED BY COORDINATE")
        elif (
            removed_stable == stable_unavailable
            and existing_stable == stable_unavailable
            and removed_ref is not existing_ref
        ):
            debug_print("DISTINCT REFERENCES MERGED BY COORDINATE")

    if len(kept_records) != len(cleaned_items):
        debug_print(
            "DIAGNOSTIC COUNT MISMATCH | Simulated clean count: {} | "
            "Actual clean count: {}".format(
                len(kept_records),
                len(cleaned_items)
            )
        )

    debug_print("=== END CLEAN_ITEMS REFERENCE DIAGNOSTIC ===")


def log_dimension_segment_diagnostic(
    chain_type,
    dimension,
    refs
):
    if not DEBUG:
        return

    try:
        reference_count = refs.Size
        expected_segment_count = max(
            reference_count - 1,
            0
        )

        try:
            actual_segment_count = dimension.Segments.Size
        except:
            actual_segment_count = -1

        debug_print("=== REVIT DIMENSION SEGMENT DIAGNOSTIC ===")
        debug_print("Chain type: {}".format(chain_type))
        debug_print(
            "Dimension ID: {}".format(
                dimension.Id.ToString()
            )
        )
        debug_print(
            "Submitted ReferenceArray count: {}".format(
                reference_count
            )
        )
        debug_print(
            "Expected segment count: {}".format(
                expected_segment_count
            )
        )
        debug_print(
            "Dimension.Segments.Size: {}".format(
                actual_segment_count
            )
        )

        if actual_segment_count != expected_segment_count:
            debug_print("REVIT DIMENSION SEGMENT COUNT MISMATCH")

        debug_print("=== END REVIT DIMENSION SEGMENT DIAGNOSTIC ===")

    except Exception as diagnostic_error:
        debug_print(
            "DIMENSION SEGMENT DIAGNOSTIC FAILED: {}".format(
                str(diagnostic_error)
            )
        )


def reference_array_from_items(items):
    references = DB.ReferenceArray()

    for coordinate, reference in items:
        references.Append(reference)

    return references


def dimension_segment_values(dimension):
    values = []

    try:
        segments = dimension.Segments
        segment_count = segments.Size
    except:
        segments = None
        segment_count = 0

    if segment_count > 0:
        for index in range(segment_count):
            try:
                values.append(
                    segments.get_Item(index).Value
                )
            except:
                values.append(None)

        return values

    try:
        values.append(dimension.Value)
    except:
        values.append(None)

    return values


def zero_segment_removal_indices(items, segment_values):
    result = set()

    if len(segment_values) != len(items) - 1:
        return result

    last_item_index = len(items) - 1

    for segment_index, value in enumerate(segment_values):
        if value is None:
            continue

        if abs(value) > CHAIN_REFERENCE_MIN_SPACING:
            continue

        right_index = segment_index + 1

        # Zincirin iki dis sinirini koru. Sondaki sifir segmentte
        # son referans yerine onun solundaki cakisan referansi ele.
        if right_index == last_item_index:
            removal_index = segment_index
        else:
            removal_index = right_index

        result.add(removal_index)

    return result


def create_dimension_without_zero_segments(
    dimension_line,
    items
):
    """Revit'in gercek segmentlerini sinar ve sifir aralikli refleri ayiklar."""
    working_items = list(items)
    removed_count = 0

    while len(working_items) >= 2:
        references = reference_array_from_items(
            working_items
        )
        subtransaction = DB.SubTransaction(doc)

        try:
            subtransaction.Start()
            dimension = doc.Create.NewDimension(
                view,
                dimension_line,
                references
            )
            doc.Regenerate()
            segment_values = dimension_segment_values(
                dimension
            )
            removal_indices = zero_segment_removal_indices(
                working_items,
                segment_values
            )

            if len(removal_indices) == 0:
                subtransaction.Commit()
                return (
                    dimension,
                    references,
                    working_items,
                    removed_count
                )

            subtransaction.RollBack()

        except:
            try:
                subtransaction.RollBack()
            except:
                pass

            raise

        for removal_index in sorted(
            removal_indices,
            reverse=True
        ):
            if (
                removal_index >= 0
                and removal_index < len(working_items)
            ):
                working_items.pop(removal_index)
                removed_count += 1

    return None, None, working_items, removed_count


def finish_scan_band(wall_direction, scan_value):
    events = []

    for wall in basic_straight_walls:
        info = wall_info(wall)

        if info["yon"] != wall_direction:
            continue

        if wall_direction == "DIKEY":
            events.extend([
                info["p0"].Y,
                info["p1"].Y
            ])
        else:
            events.extend([
                info["p0"].X,
                info["p1"].X
            ])

    events.sort()
    unique_events = []

    for value in events:
        if (
            len(unique_events) == 0
            or abs(value - unique_events[-1]) > TOL
        ):
            unique_events.append(value)

    for i in range(len(unique_events) - 1):
        start = unique_events[i]
        end = unique_events[i + 1]

        if (
            scan_value >= start - TOL
            and scan_value <= end + TOL
        ):
            return start, end

    return None


def scan_owns_parallel_coordinate(
    wall_direction,
    scan_value,
    perpendicular_coord
):
    owners = []

    for candidate_scan in finish_scan_values(wall_direction):
        band = finish_scan_band(
            wall_direction,
            candidate_scan
        )

        if band is None:
            continue

        if (
            perpendicular_coord >= band[0] - TOL
            and perpendicular_coord <= band[1] + TOL
        ):
            owners.append(candidate_scan)

    if len(owners) == 0:
        return False

    owners.sort(
        key=lambda owner: (
            abs(owner - perpendicular_coord),
            owner
        )
    )

    return abs(owners[0] - scan_value) <= TOL


def coordinate_is_on_room_side(
    source_surface_coordinate,
    room_side_sign,
    candidate_coordinate
):
    """Aday koordinatin yalnizca Room yuzunun baktigi tarafta oldugunu sinar."""
    if (
        source_surface_coordinate is None
        or room_side_sign == 0
    ):
        return True

    return (
        candidate_coordinate
        - source_surface_coordinate
    ) * room_side_sign >= -ROOM_CHAIN_TRACK_TOL


def finish_parallel_endpoint_candidates(
    descriptor,
    wall_direction
):
    direction = descriptor["direction"]
    scan_value = descriptor["scan_coordinate"]
    scan_min = descriptor["scan_min"]
    scan_max = descriptor["scan_max"]
    first_wall = descriptor["first_exterior_boundary"]
    last_wall = descriptor["last_exterior_boundary"]

    if direction == "X":
        parallel_wall_direction = "YATAY"
        first_coord = wall_info(first_wall)["mid_x"]
        last_coord = wall_info(last_wall)["mid_x"]
    else:
        parallel_wall_direction = "DIKEY"
        first_coord = wall_info(first_wall)["mid_y"]
        last_coord = wall_info(last_wall)["mid_y"]

    boundary_min = min(first_coord, last_coord)
    boundary_max = max(first_coord, last_coord)
    result = []
    direction_rejected_wall_count = 0
    terminating_room_side_rejected_count = 0

    for wall in basic_straight_walls:
        info = wall_info(wall)

        if info["yon"] != parallel_wall_direction:
            continue

        if direction == "X":
            perpendicular_coord = info["mid_y"]
        else:
            perpendicular_coord = info["mid_x"]

        if (
            perpendicular_coord < scan_min - TOL
            or perpendicular_coord > scan_max + TOL
        ):
            continue

        source_surface_coordinate = descriptor.get(
            "source_surface_coordinate"
        )
        room_side_sign = descriptor.get(
            "room_side_sign",
            0
        )

        if not coordinate_is_on_room_side(
            source_surface_coordinate,
            room_side_sign,
            perpendicular_coord
        ):
            direction_rejected_wall_count += 1
            continue

        scan_owner = scan_owns_parallel_coordinate(
            wall_direction,
            scan_value,
            perpendicular_coord
        )

        # Room yuzeyinden uretilen bir zincirde, ayni scan bandini
        # kesen paralel duvar bitisleri o yuzey zincirine aittir.
        # Eski global owner secimi merdiven duvarlarini tek bir hatta
        # kilitleyip diger zincirlerde kopukluk olusturuyordu.
        if direction == "X":
            active_room_tracks = room_chain_tracks_x
        else:
            active_room_tracks = room_chain_tracks_y

        for active_track in active_room_tracks:
            if (
                abs(
                    active_track["scan_coordinate"]
                    - scan_value
                ) <= ROOM_CHAIN_TRACK_TOL
            ):
                scan_owner = True
                break

        if scan_owner:
            for candidate in wall_free_end_face_candidates(wall):
                coord = candidate["coordinate"]

                if (
                    coord < boundary_min - TOL
                    or coord > boundary_max + TOL
                ):
                    continue

                result.append(candidate)

        for end_index in [0, 1]:
            candidate = wall_endpoint_terminating_core_candidate(
                wall,
                end_index,
                direction
            )

            if candidate is None:
                continue

            if not wall_penetrates_room_side(
                candidate["terminating_wall"],
                wall_direction,
                scan_value,
                room_side_sign
            ):
                terminating_room_side_rejected_count += 1
                debug_print(
                    "TERMINATING CORE REJECTED BY VISIBLE ROOM SIDE | "
                    "Parallel Wall: {} | End: {} | "
                    "Terminating Wall: {}".format(
                        wall.Id.ToString(),
                        end_index,
                        candidate[
                            "terminating_wall"
                        ].Id.ToString()
                    )
                )
                continue

            coord = candidate["coordinate"]

            if (
                coord < boundary_min - TOL
                or coord > boundary_max + TOL
            ):
                continue

            result.append(candidate)
            debug_print(
                "TERMINATING WALL CORE ADDED | Direction: {} | "
                "Scan: {:.6f} | Parallel Wall: {} | End: {} | "
                "Terminating Wall: {} | Core coordinate: {:.9f}".format(
                    direction,
                    scan_value,
                    wall.Id.ToString(),
                    end_index,
                    candidate["terminating_wall"].Id.ToString(),
                    coord
                )
            )

    result.sort(
        key=lambda candidate: (
            candidate["coordinate"],
            candidate["wall_id"],
            candidate["end_index"]
        )
    )

    descriptor["direction_rejected_parallel_wall_count"] = (
        direction_rejected_wall_count
    )
    descriptor["terminating_room_side_rejected_count"] = (
        terminating_room_side_rejected_count
    )

    return result


def diagnostic_wall_end_cap_candidate(wall, end_index):
    """Filtrelerden once native end-cap Reference durumunu salt-okunur raporlar."""
    info = wall_info(wall)

    if info is None:
        return None

    endpoint = info["curve"].GetEndPoint(end_index)
    direction = info["direction"]
    end_face_tol = max(TOL * 5.0, 0.005)
    options = DB.Options()
    options.ComputeReferences = True

    try:
        geometry = wall.get_Geometry(options)
    except:
        geometry = None

    if geometry is None:
        return None

    candidates = []

    for geo in geometry:
        if not isinstance(geo, DB.Solid):
            continue

        if geo.Volume <= 0:
            continue

        for face in geo.Faces:
            if not isinstance(face, DB.PlanarFace):
                continue

            ref = face.Reference

            if ref is None:
                continue

            try:
                if not ref.ElementId.Equals(wall.Id):
                    continue
            except:
                continue

            try:
                if (
                    ref.ElementReferenceType
                    != DB.ElementReferenceType.REFERENCE_TYPE_SURFACE
                ):
                    continue
            except:
                pass

            dot = abs(
                face.FaceNormal.DotProduct(direction)
            )

            if dot <= 0.99:
                continue

            plane_distance = abs(
                (
                    endpoint - face.Origin
                ).DotProduct(face.FaceNormal)
            )

            if plane_distance > end_face_tol:
                continue

            try:
                area = face.Area
            except:
                area = 0.0

            candidates.append(
                (
                    plane_distance,
                    -area,
                    face,
                    ref
                )
            )

    if len(candidates) == 0:
        return None

    candidates.sort(
        key=lambda candidate: (
            candidate[0],
            candidate[1]
        )
    )
    selected = candidates[0]
    face = selected[2]
    ref = selected[3]

    if info["yon"] == "YATAY":
        coord = face.Origin.X
    else:
        coord = face.Origin.Y

    return {
        "reference": ref,
        "coordinate": coord
    }


def diagnostic_element_ids_text(element_ids):
    if len(element_ids) == 0:
        return "NONE"

    return ", ".join([
        str(element_id_key(element_id))
        for element_id in element_ids
    ])


def diagnostic_joined_ids_at_end(wall, end_index):
    location = wall.Location

    if not isinstance(location, DB.LocationCurve):
        return []

    try:
        joined_items = list(
            location.get_ElementsAtJoin(end_index)
        )
    except:
        try:
            joined_items = list(
                location.ElementsAtJoin[end_index]
            )
        except:
            joined_items = []

    wall_id = element_id_key(wall.Id)
    joined_ids = []

    for joined_item in joined_items:
        try:
            joined_id = joined_item.Id
        except:
            joined_id = joined_item

        if element_id_key(joined_id) != wall_id:
            joined_ids.append(joined_id)

    return joined_ids


def log_finish_parallel_endpoint_diagnostic(
    descriptor,
    wall_direction,
    endpoint_decisions
):
    if not DEBUG:
        return

    direction = descriptor["direction"]
    scan_value = descriptor["scan_coordinate"]
    scan_min = descriptor["scan_min"]
    scan_max = descriptor["scan_max"]
    first_wall = descriptor["first_exterior_boundary"]
    last_wall = descriptor["last_exterior_boundary"]
    if direction == "X":
        parallel_wall_direction = "YATAY"
        first_coord = wall_info(first_wall)["mid_x"]
        last_coord = wall_info(last_wall)["mid_x"]
    else:
        parallel_wall_direction = "DIKEY"
        first_coord = wall_info(first_wall)["mid_y"]
        last_coord = wall_info(last_wall)["mid_y"]

    boundary_min = min(first_coord, last_coord)
    boundary_max = max(first_coord, last_coord)
    candidate_by_key = {}

    for candidate in descriptor["finish_endpoint_candidates"]:
        candidate_by_key[
            (
                candidate["wall_id"],
                candidate["end_index"]
            )
        ] = candidate

    for wall in basic_straight_walls:
        info = wall_info(wall)

        if (
            info is None
            or info["yon"] != parallel_wall_direction
        ):
            continue

        wall_id = element_id_key(wall.Id)

        if direction == "X":
            perpendicular_coord = info["mid_y"]
        else:
            perpendicular_coord = info["mid_x"]

        inside_scan_band = (
            perpendicular_coord >= scan_min - TOL
            and perpendicular_coord <= scan_max + TOL
        )
        scan_owner = scan_owns_parallel_coordinate(
            wall_direction,
            scan_value,
            perpendicular_coord
        )

        for end_index in [0, 1]:
            key = (
                wall_id,
                end_index
            )
            endpoint = info["curve"].GetEndPoint(end_index)
            joined_ids = diagnostic_joined_ids_at_end(
                wall,
                end_index
            )
            touching_wall = wall_endpoint_touching_wall(
                wall,
                endpoint
            )
            raw_candidate = diagnostic_wall_end_cap_candidate(
                wall,
                end_index
            )
            actual_candidate = candidate_by_key.get(key)

            if actual_candidate is not None:
                candidate = actual_candidate
            else:
                candidate = raw_candidate

            is_terminating_core = (
                actual_candidate is not None
                and actual_candidate.get(
                    "reference_kind"
                ) == "TERMINATING_CORE"
            )

            if candidate is None:
                native_reference_found = False
                stable = "NONE"

                if direction == "X":
                    endpoint_coord = endpoint.X
                else:
                    endpoint_coord = endpoint.Y
            else:
                native_reference_found = True
                stable = reference_stable_text(
                    candidate["reference"]
                )
                endpoint_coord = candidate["coordinate"]

            inside_exterior_boundaries = (
                endpoint_coord >= boundary_min - TOL
                and endpoint_coord <= boundary_max + TOL
            )
            decision = endpoint_decisions.get(key)
            duplicate_coordinate = False
            duplicate_coordinate_text = "NONE"
            duplicate_stable = False

            if decision is not None:
                duplicate_coordinate = decision[
                    "duplicate_coordinate"
                ]
                duplicate_stable = decision[
                    "duplicate_stable"
                ]

                if decision["duplicate_coordinate_match"] is not None:
                    duplicate_coordinate_text = "{:.9f}".format(
                        decision["duplicate_coordinate_match"]
                    )

            joined_confirmed = wall_joined_endpoint_confirmed(
                wall,
                endpoint,
                joined_ids
            )

            if not inside_scan_band:
                accepted = False
                reason = "OUTSIDE SCAN BAND"
            elif not scan_owner and not is_terminating_core:
                accepted = False
                reason = "SCAN BAND OWNED BY ANOTHER FINISH DESCRIPTOR"
            elif (
                touching_wall is not None
                and not is_terminating_core
            ):
                accepted = False
                reason = "ENDPOINT TOUCHES WALL {}".format(
                    touching_wall.Id.ToString()
                )
            elif (
                len(joined_ids) > 0
                and joined_confirmed
                and not is_terminating_core
            ):
                accepted = False
                reason = "JOINED END (geometrically confirmed)"
            elif not native_reference_found:
                accepted = False
                reason = "NATIVE END-CAP FACE REFERENCE NOT FOUND"
            elif not inside_exterior_boundaries:
                accepted = False
                reason = "OUTSIDE EXTERIOR BOUNDARIES"
            elif decision is None:
                accepted = False
                reason = "ENDPOINT FILTER STATE NOT RECORDED"
            elif duplicate_coordinate:
                accepted = False
                reason = "DUPLICATE COORDINATE"
            elif duplicate_stable:
                accepted = False
                reason = "DUPLICATE STABLE REFERENCE"
            else:
                accepted = decision["accepted"]

                if accepted:
                    reason = "ACCEPTED"
                else:
                    reason = "REJECTED BY FINISH ENDPOINT FILTER"

            if touching_wall is None:
                touching_text = "NONE"
            else:
                touching_text = "Wall {}".format(
                    touching_wall.Id.ToString()
                )

            debug_print("=== FINISH ENDPOINT DIAGNOSTIC ===")
            debug_print("Wall ID: {}".format(wall.Id.ToString()))
            debug_print("End index: {}".format(end_index))
            debug_print(
                "Endpoint XYZ: ({:.9f}, {:.9f}, {:.9f})".format(
                    endpoint.X,
                    endpoint.Y,
                    endpoint.Z
                )
            )
            debug_print(
                "End-cap native Reference found: {}".format(
                    "YES" if native_reference_found else "NO"
                )
            )
            debug_print("Stable representation: {}".format(stable))
            debug_print("Descriptor direction: {}".format(direction))
            debug_print(
                "Descriptor scan coordinate: {:.6f}".format(
                    scan_value
                )
            )
            debug_print(
                "Inside scan band: {} | Band: [{:.6f}, {:.6f}]".format(
                    "YES" if inside_scan_band else "NO",
                    scan_min,
                    scan_max
                )
            )
            debug_print(
                "Scan band owner: {}".format(
                    "YES" if scan_owner else "NO"
                )
            )
            debug_print(
                "Inside exterior boundaries: {} | Interval: "
                "[{:.6f}, {:.6f}]".format(
                    "YES" if inside_exterior_boundaries else "NO",
                    boundary_min,
                    boundary_max
                )
            )
            debug_print(
                "ElementsAtJoin[{}]: {}".format(
                    end_index,
                    diagnostic_element_ids_text(joined_ids)
                )
            )
            debug_print(
                "wall_endpoint_touching_wall(): {}".format(
                    touching_text
                )
            )
            debug_print(
                "wall_joined_endpoint_confirmed(): {}".format(
                    "YES" if joined_confirmed else "NO"
                )
            )
            debug_print(
                "Rejected by duplicate coordinate: {} | "
                "Existing coordinate: {}".format(
                    "YES" if duplicate_coordinate else "NO",
                    duplicate_coordinate_text
                )
            )
            debug_print(
                "Rejected by duplicate stable representation: {}".format(
                    "YES" if duplicate_stable else "NO"
                )
            )

            if accepted:
                debug_print(
                    "ENDPOINT ACCEPTED | Wall {} | End {} | "
                    "Coordinate: {:.9f}".format(
                        wall.Id.ToString(),
                        end_index,
                        endpoint_coord
                    )
                )
            else:
                debug_print(
                    "ENDPOINT REJECTED | Wall {} | End {} | "
                    "Reason: {}".format(
                        wall.Id.ToString(),
                        end_index,
                        reason
                    )
                )

            debug_print("=== END FINISH ENDPOINT DIAGNOSTIC ===")


def finish_scan_values(wall_direction):
    """Duvar uc araliklarindan full Finish zinciri tarama koordinatlari uretir."""
    events = []

    for wall in basic_straight_walls:
        info = wall_info(wall)

        if info["yon"] != wall_direction:
            continue

        if wall_direction == "DIKEY":
            events.extend([
                info["p0"].Y,
                info["p1"].Y
            ])
        else:
            events.extend([
                info["p0"].X,
                info["p1"].X
            ])

    events.sort()
    unique_events = []

    for value in events:
        if (
            len(unique_events) == 0
            or abs(value - unique_events[-1]) > TOL
        ):
            unique_events.append(value)

    result = []

    for i in range(len(unique_events) - 1):
        start = unique_events[i]
        end = unique_events[i + 1]

        if end - start <= TOL:
            continue

        scan_value = (start + end) / 2.0
        exterior_coords = []

        for wall in basic_straight_walls:
            info = wall_info(wall)

            if info["yon"] != wall_direction:
                continue

            if wall_direction == "DIKEY":
                intersects = crosses_y(wall, scan_value)
            else:
                intersects = crosses_x(wall, scan_value)

            if intersects and wall_is_exterior(wall):
                if wall_direction == "DIKEY":
                    exterior_coords.append(info["mid_x"])
                else:
                    exterior_coords.append(info["mid_y"])

        if (
            len(exterior_coords) >= 2
            and max(exterior_coords) - min(exterior_coords) > TOL
        ):
            result.append(scan_value)

    return result


def full_finish_chain(
    wall_direction,
    scan_value,
    room_track=None
):
    """Gercek exterior uclar arasindaki tum kesen duvarlarin Finish yuzlerini toplar."""
    debug_print("FULL_FINISH_CHAIN CALLED")
    cut_walls = []
    exterior_cut_walls = []
    room_side_rejected_cut_wall_ids = []

    if wall_direction == "DIKEY":
        axis = "X"
    else:
        axis = "Y"

    for wall in basic_straight_walls:
        info = wall_info(wall)

        if info["yon"] != wall_direction:
            continue

        if wall_direction == "DIKEY":
            intersects = crosses_y(wall, scan_value)
            wall_coord = info["mid_x"]
        else:
            intersects = crosses_x(wall, scan_value)
            wall_coord = info["mid_y"]

        if not intersects:
            continue

        if (
            room_track is not None
            and not wall_penetrates_room_side(
                wall,
                wall_direction,
                scan_value,
                room_track.get("room_side_sign", 0)
            )
        ):
            room_side_rejected_cut_wall_ids.append(
                element_id_key(wall.Id)
            )
            debug_print(
                "TOUCH-ONLY WALL REJECTED | Wall: {} | "
                "Direction: {} | Scan: {:.6f} | Room side: {}".format(
                    wall.Id.ToString(),
                    wall_direction,
                    scan_value,
                    room_track.get("room_side_sign", 0)
                )
            )
            continue

        cut_walls.append((wall_coord, wall))

        if wall_is_exterior(wall):
            exterior_cut_walls.append((wall_coord, wall))

    sorted_cut_walls = sorted(
        cut_walls,
        key=lambda item: item[0]
    )
    exterior_cut_walls.sort(key=lambda item: item[0])

    if room_track is not None and len(sorted_cut_walls) >= 2:
        preferred_cut_walls = [
            item
            for item in sorted_cut_walls
            if element_id_key(item[1].Id)
            in room_track.get(
                "boundary_end_wall_ids",
                set()
            )
        ]
        boundary_candidates = (
            preferred_cut_walls
            if len(preferred_cut_walls) >= 2
            else sorted_cut_walls
        )
        start_candidate = min(
            boundary_candidates,
            key=lambda item: abs(
                item[0] - room_track["span_start"]
            )
        )
        end_candidate = min(
            boundary_candidates,
            key=lambda item: abs(
                item[0] - room_track["span_end"]
            )
        )
        boundary_tolerance = max(
            DB.UnitUtils.ConvertToInternalUnits(
                750.0,
                DB.UnitTypeId.Millimeters
            ),
            start_candidate[1].Width,
            end_candidate[1].Width
        )

        if (
            not start_candidate[1].Id.Equals(
                end_candidate[1].Id
            )
            and abs(
                start_candidate[0]
                - room_track["span_start"]
            ) <= boundary_tolerance
            and abs(
                end_candidate[0]
                - room_track["span_end"]
            ) <= boundary_tolerance
        ):
            exterior_cut_walls = sorted(
                [
                    start_candidate,
                    end_candidate
                ],
                key=lambda item: item[0]
            )

    finish_ref_counts_by_wall = {}

    if DEBUG:
        for wall_coord, wall in sorted_cut_walls:
            wall_id = element_id_key(wall.Id)
            exterior_ref_count = 0
            interior_ref_count = 0

            try:
                exterior_ref_count = DB.HostObjectUtils.GetSideFaces(
                    wall,
                    DB.ShellLayerType.Exterior
                ).Count
            except:
                pass

            try:
                interior_ref_count = DB.HostObjectUtils.GetSideFaces(
                    wall,
                    DB.ShellLayerType.Interior
                ).Count
            except:
                pass

            finish_ref_counts_by_wall[wall_id] = (
                exterior_ref_count
                + interior_ref_count
            )

    debug_print("=== FINISH CHAIN DIAGNOSTIC ===")
    debug_print("Direction: {}".format(axis))
    debug_print("Scan coordinate: {:.6f}".format(scan_value))
    debug_print(
        "Intersecting Wall IDs: {}".format(
            ", ".join([
                wall.Id.ToString()
                for wall_coord, wall in sorted_cut_walls
            ])
        )
    )

    if DEBUG:
        for wall_coord, wall in sorted_cut_walls:
            wall_id = element_id_key(wall.Id)

            try:
                function_name = wall.WallType.Function.ToString()
            except:
                function_name = str(wall.WallType.Function)

            debug_print(
                "Wall {} | WallType.Function: {} | "
                "Finish reference count: {}".format(
                    wall.Id.ToString(),
                    function_name,
                    finish_ref_counts_by_wall[wall_id]
                )
            )

    debug_print(
        "Exterior Wall IDs: {}".format(
            ", ".join([
                wall.Id.ToString()
                for wall_coord, wall in exterior_cut_walls
            ])
        )
    )

    if (
        len(exterior_cut_walls) < 2
        or exterior_cut_walls[-1][0]
        - exterior_cut_walls[0][0] <= TOL
    ):
        debug_print("First exterior boundary: NONE")
        debug_print("Last exterior boundary: NONE")
        debug_print("Walls in continuous chain: NONE")
        debug_print("Final ReferenceArray reference count: 0")
        debug_print("Chain signature: NONE")
        debug_print(
            "CHAIN REJECTED - TWO EXTERIOR BOUNDARIES NOT FOUND"
        )
        debug_print("=== END FINISH CHAIN DIAGNOSTIC ===")
        return None

    start_coord = exterior_cut_walls[0][0]
    end_coord = exterior_cut_walls[-1][0]
    start_wall = exterior_cut_walls[0][1]
    end_wall = exterior_cut_walls[-1][1]

    chain_walls = []

    for wall_coord, wall in cut_walls:
        if (
            wall_coord >= start_coord - TOL
            and wall_coord <= end_coord + TOL
        ):
            chain_walls.append((wall_coord, wall))

    chain_walls.sort(key=lambda item: item[0])
    descriptor_walls = [
        wall
        for wall_coord, wall in chain_walls
    ]
    scan_band = finish_scan_band(
        wall_direction,
        scan_value
    )

    if scan_band is None:
        scan_band = (
            scan_value,
            scan_value
        )

    descriptor = {
        "direction": axis,
        "scan_coordinate": scan_value,
        "scan_min": scan_band[0],
        "scan_max": scan_band[1],
        "room_ids": (
            tuple(sorted(room_track["room_ids"]))
            if room_track is not None
            else tuple()
        ),
        "span_start": (
            room_track["span_start"]
            if room_track is not None
            else start_coord
        ),
        "span_end": (
            room_track["span_end"]
            if room_track is not None
            else end_coord
        ),
        "room_side_sign": (
            room_track["room_side_sign"]
            if room_track is not None
            else 0
        ),
        "source_surface_coordinate": (
            room_track["source_surface_coordinate"]
            if room_track is not None
            else None
        ),
        "room_side_rejected_cut_wall_ids": (
            room_side_rejected_cut_wall_ids
        ),
        "first_exterior_boundary": start_wall,
        "last_exterior_boundary": end_wall,
        "wall_ids": [
            element_id_key(wall.Id)
            for wall in descriptor_walls
        ],
        "walls": descriptor_walls
    }
    debug_print("ABOUT TO COLLECT PARALLEL ENDPOINTS")
    endpoint_items = finish_parallel_endpoint_candidates(
        descriptor,
        wall_direction
    )
    debug_print(
        "PARALLEL ENDPOINT COLLECTION RETURNED: {}".format(
            len(endpoint_items)
        )
    )
    descriptor["finish_endpoint_candidates"] = endpoint_items
    items = []
    raw_reference_records = []
    chain_faces_by_wall = {}

    debug_print(
        "First exterior boundary: {}".format(
            start_wall.Id.ToString()
        )
    )
    debug_print(
        "Last exterior boundary: {}".format(
            end_wall.Id.ToString()
        )
    )
    debug_print(
        "Walls in continuous chain: {}".format(
            ", ".join([
                wall.Id.ToString()
                for wall_coord, wall in chain_walls
            ])
        )
    )

    missing_wall_ids = set()

    if DEBUG:
        chain_wall_ids = set([
            element_id_key(wall.Id)
            for wall_coord, wall in chain_walls
        ])

        for wall_coord, wall in sorted_cut_walls:
            wall_id = element_id_key(wall.Id)

            if (
                wall_coord >= start_coord - TOL
                and wall_coord <= end_coord + TOL
                and wall_id not in chain_wall_ids
            ):
                missing_wall_ids.add(wall_id)
                debug_print(
                    "WALL {} MISSING FROM CONTINUOUS CHAIN".format(
                        wall.Id.ToString()
                    )
                )

    for wall in descriptor["walls"]:
        wall_id = element_id_key(wall.Id)
        faces = wall_finish_faces(wall, axis)
        chain_faces_by_wall[wall_id] = faces

        for face in faces:
            items.append(face)
            raw_reference_records.append(
                (
                    face[0],
                    face[1],
                    wall_id
                )
            )

    side_face_items = list(items)
    side_face_reference_count = len(side_face_items)
    accepted_endpoint_candidates = []
    endpoint_decisions = {}
    stable_unavailable = (
        "<STABLE REPRESENTATION UNAVAILABLE>"
    )
    occupied_stable_refs = set([
        stable
        for stable in [
            reference_stable_text(ref)
            for coord, ref in items
        ]
        if stable != stable_unavailable
    ])

    for candidate in descriptor["finish_endpoint_candidates"]:
        coord = candidate["coordinate"]
        ref = candidate["reference"]
        stable = reference_stable_text(ref)
        duplicate_coord = False
        duplicate_coordinate_match = None

        for existing_coord, existing_ref in items:
            if abs(coord - existing_coord) < TOL:
                duplicate_coord = True
                duplicate_coordinate_match = existing_coord
                break

        duplicate_stable = (
            stable != stable_unavailable
            and stable in occupied_stable_refs
        )
        endpoint_decision = {
            "accepted": False,
            "duplicate_coordinate": duplicate_coord,
            "duplicate_coordinate_match": duplicate_coordinate_match,
            "duplicate_stable": duplicate_stable
        }
        endpoint_decisions[
            (
                candidate["wall_id"],
                candidate["end_index"]
            )
        ] = endpoint_decision

        if duplicate_coord or duplicate_stable:
            debug_print(
                "FINISH ENDPOINT SKIPPED AS DUPLICATE | "
                "Direction: {} | Scan: {:.6f} | Wall ID: {} | "
                "End: {} | Coordinate: {:.9f} | Stable: {}".format(
                    descriptor["direction"],
                    descriptor["scan_coordinate"],
                    candidate["wall_id"],
                    candidate["end_index"],
                    coord,
                    stable
                )
            )
            continue

        items.append(
            (
                coord,
                ref
            )
        )
        raw_reference_records.append(
            (
                coord,
                ref,
                candidate["wall_id"]
            )
        )
        if stable != stable_unavailable:
            occupied_stable_refs.add(stable)
        accepted_endpoint_candidates.append(candidate)
        endpoint_decision["accepted"] = True

        debug_print(
            "FINISH FREE ENDPOINT ADDED | Direction: {} | "
            "Scan: {:.6f} | Band: [{:.6f}, {:.6f}] | "
            "Wall ID: {} | End: {} | Coordinate: {:.9f} | "
            "Stable: {}".format(
                descriptor["direction"],
                descriptor["scan_coordinate"],
                descriptor["scan_min"],
                descriptor["scan_max"],
                candidate["wall_id"],
                candidate["end_index"],
                coord,
                stable
            )
        )

    descriptor["accepted_finish_endpoint_candidates"] = (
        accepted_endpoint_candidates
    )
    log_finish_parallel_endpoint_diagnostic(
        descriptor,
        wall_direction,
        endpoint_decisions
    )

    items = clean_items(items)
    log_clean_items_diagnostic(
        "Finish",
        descriptor,
        raw_reference_records,
        items
    )
    debug_print("=== FINISH CHAIN REFERENCE SUMMARY ===")
    debug_print("Direction: {}".format(descriptor["direction"]))
    debug_print(
        "Scan coordinate: {:.6f}".format(
            descriptor["scan_coordinate"]
        )
    )
    debug_print(
        "Side-face reference count: {}".format(
            side_face_reference_count
        )
    )
    debug_print(
        "Accepted endpoint reference count: {}".format(
            len(accepted_endpoint_candidates)
        )
    )
    debug_print(
        "Final ReferenceArray count: {}".format(
            len(items)
        )
    )
    debug_print("=== END FINISH CHAIN REFERENCE SUMMARY ===")

    if DEBUG:
        final_refs = [ref for coord, ref in items]

        for wall_coord, wall in chain_walls:
            wall_id = element_id_key(wall.Id)
            wall_has_final_ref = False

            for coord, wall_ref in chain_faces_by_wall[wall_id]:
                for final_ref in final_refs:
                    if wall_ref is final_ref:
                        wall_has_final_ref = True
                        break

                if wall_has_final_ref:
                    break

            if (
                not wall_has_final_ref
                and wall_id not in missing_wall_ids
            ):
                missing_wall_ids.add(wall_id)
                debug_print(
                    "WALL {} MISSING FROM CONTINUOUS CHAIN".format(
                        wall.Id.ToString()
                    )
                )

    if len(items) < 2:
        rejected_signature = (
            axis,
            chain_signature(items)
        )
        debug_print(
            "Final ReferenceArray reference count: {}".format(
                len(items)
            )
        )
        debug_print(
            "Chain signature: {}".format(
                str(rejected_signature)
            )
        )
        debug_print("=== END FINISH CHAIN DIAGNOSTIC ===")
        return None

    return {
        "items": items,
        "start_wall": start_wall,
        "descriptor": descriptor
    }


# ============================================================
# 11. ROOM BOUNDARY OPTIONS + BINA SINIR DUVARLARI
# ============================================================

boundary_options = DB.SpatialElementBoundaryOptions()

boundary_options.SpatialElementBoundaryLocation = \
    DB.SpatialElementBoundaryLocation.Finish

room_boundary_wall_ids = set()

for room in rooms:
    try:
        loops = room.GetBoundarySegments(
            boundary_options
        )
    except:
        loops = None

    if loops is None:
        continue

    for loop in loops:
        for segment in loop:
            element = doc.GetElement(
                segment.ElementId
            )

            if isinstance(element, DB.Wall):
                room_boundary_wall_ids.add(
                    element_id_key(element.Id)
                )


# Room noktasi yoksa tek bir merkez taramasi olustur.
if len(scan_x) == 0 or len(scan_y) == 0:
    all_x = []
    all_y = []

    for wall in basic_straight_walls:
        info = wall_info(wall)

        all_x.extend([
            info["p0"].X,
            info["p1"].X
        ])

        all_y.extend([
            info["p0"].Y,
            info["p1"].Y
        ])

    if len(all_x) > 0:
        scan_x = [
            (
                min(all_x)
                + max(all_x)
            ) / 2.0
        ]

    if len(all_y) > 0:
        scan_y = [
            (
                min(all_y)
                + max(all_y)
            ) / 2.0
        ]


# ============================================================
# 12. V6 SAYACLAR
# ============================================================

opening_chain_count = 0
no_opening_chain_count = 0
core_chain_count = 0
column_reference_count = 0
duplicate_room_chain_count = 0
smart_preselection_rejected_count = 0
direction_rejected_parallel_wall_count = 0
room_side_rejected_cut_wall_count = 0
terminating_room_side_rejected_count = 0
zero_segment_reference_removal_count = 0
selected_interior_surface_keys = set()
skipped_count = 0

core_signatures = set()
room_chain_reference_signatures_x = set()
room_chain_reference_signatures_y = set()
created_chain_visual_registry_x = {}
created_chain_visual_registry_y = {}
created_chain_geometry_registry_x = []
created_chain_geometry_registry_y = []
created_room_topology_chains = set()
processed_wall_segments = set()

shared_chain_descriptors_x = []
shared_chain_descriptors_y = []

room_chain_tracks_x = []
room_chain_tracks_y = []

diagnostic_finish_scans_x = []
diagnostic_finish_scans_y = []
diagnostic_core_scans_x = []
diagnostic_core_scans_y = []


# ============================================================
# 13. V6 DIMENSIONLARI
# ============================================================

prepare_opening_reference_cache()
prepare_column_face_cache()

with revit.Transaction(
    "Benay Interior Dimension V19 Multi Height Wall Test"
):

    # ========================================================
    # A. ROOM-SIDE 40/80 CM CONTINUOUS CHAIN TRACKLERI
    # ========================================================
    # Bu blok artik tekil dimension olusturmaz. Her Room boundary
    # segmentinin Room tarafinda, 40 cm offsette ortak bir scan track
    # toplar. Host duvarin test edilmis gercek bosluk yuzleri bu tracke
    # kaydedilir; ikinci Core hatti 80 cm offsette olusturulur.

    for room in rooms:
        room_id = element_id_key(room.Id)

        try:
            loops = room.GetBoundarySegments(
                boundary_options
            )
        except:
            loops = None

        if loops is None:
            continue

        for loop in loops:
            segments = [segment for segment in loop]
            count = len(segments)

            if count == 0:
                continue

            for i in range(count):
                segment = segments[i]

                boundary_end_wall_ids = set()

                for neighbor_index in [
                    (i - 1) % count,
                    (i + 1) % count
                ]:
                    neighbor_element = doc.GetElement(
                        segments[neighbor_index].ElementId
                    )

                    if isinstance(neighbor_element, DB.Wall):
                        boundary_end_wall_ids.add(
                            element_id_key(
                                neighbor_element.Id
                            )
                        )

                wall = doc.GetElement(
                    segment.ElementId
                )

                if not isinstance(wall, DB.Wall):
                    continue

                curve = segment.GetCurve()

                if not isinstance(curve, DB.Line):
                    continue

                p0 = curve.GetEndPoint(0)
                p1 = curve.GetEndPoint(1)

                dx = abs(p1.X - p0.X)
                dy = abs(p1.Y - p0.Y)

                if not (
                    dx < TOL
                    or dy < TOL
                ):
                    continue

                line = room_side_dimension_line(
                    room,
                    curve,
                    ROOM_CHAIN_OFFSET
                )
                line_start = line.GetEndPoint(0)

                if dy < TOL:
                    if line_start.Y - p0.Y >= 0:
                        room_side_sign = 1.0
                    else:
                        room_side_sign = -1.0

                    secondary_coordinate = (
                        line_start.Y
                        + room_side_sign
                        * ROOM_CHAIN_OFFSET
                    )
                    track = room_chain_track(
                        room_chain_tracks_x,
                        line_start.Y,
                        secondary_coordinate,
                        room_id,
                        p0.X,
                        p1.X,
                        boundary_end_wall_ids,
                        element_id_key(wall.Id),
                        wall_is_exterior(wall),
                        room_side_sign,
                        p0.Y
                    )
                    axis = "X"
                else:
                    if line_start.X - p0.X >= 0:
                        room_side_sign = 1.0
                    else:
                        room_side_sign = -1.0

                    secondary_coordinate = (
                        line_start.X
                        + room_side_sign
                        * ROOM_CHAIN_OFFSET
                    )
                    track = room_chain_track(
                        room_chain_tracks_y,
                        line_start.X,
                        secondary_coordinate,
                        room_id,
                        p0.Y,
                        p1.Y,
                        boundary_end_wall_ids,
                        element_id_key(wall.Id),
                        wall_is_exterior(wall),
                        room_side_sign,
                        p0.X
                    )
                    axis = "Y"

                add_opening_items_to_track(
                    track,
                    wall,
                    curve,
                    axis
                )


    # ========================================================
    # A2. IKI ASAMALI AKILLI ADAY SECIMI
    # ========================================================
    # Bu asamada henuz modele dimension yazilmaz. Tum adaylar
    # kurulur; ayni Room + yon + fiziksel araliktaki TOTAL zincirlerden
    # en kapsamli olan, DETAIL zincirlerden ise benzersiz olan secilir.

    smart_profiles_x = []

    for smart_y, smart_track in room_chain_jobs(
        room_chain_tracks_x
    ):
        smart_profiles_x.extend(
            smart_chain_candidate_profiles(
                "DIKEY",
                smart_y,
                smart_track
            )
        )

    smart_allowed_x, smart_rejected_x = (
        select_smart_chain_candidates(
            smart_profiles_x
        )
    )

    smart_profiles_y = []

    for smart_x, smart_track in room_chain_jobs(
        room_chain_tracks_y
    ):
        smart_profiles_y.extend(
            smart_chain_candidate_profiles(
                "YATAY",
                smart_x,
                smart_track
            )
        )

    smart_allowed_y, smart_rejected_y = (
        select_smart_chain_candidates(
            smart_profiles_y
        )
    )
    smart_preselection_rejected_count = (
        smart_rejected_x
        + smart_rejected_y
    )

    for selected_profile in (
        smart_profiles_x
        + smart_profiles_y
    ):
        selected_key = (
            selected_profile["track_token"],
            selected_profile["variant"]
        )

        if (
            selected_key not in (
                smart_allowed_x
                if selected_profile["axis"] == "X"
                else smart_allowed_y
            )
            or not selected_profile[
                "force_interior_surface"
            ]
        ):
            continue

        selected_interior_surface_keys.update(
            selected_profile["interior_surface_keys"]
        )

    duplicate_room_chain_count += (
        smart_preselection_rejected_count
    )


    # ========================================================
    # B. KESINTISIZ FULL CORE ZINCIRLERI (Finish kullanilmiyor)
    # ========================================================
    # V6 KURALI (Core boundary referans - Finish artik olusturulmuyor):
    # - Zincir ilk dis sinirdan karsi dis sinira kadar kesilmez.
    # - Ilk ve son dis duvarin IKI Core yuzu de zincire girer.
    # - Aradaki HER kesen duvarin iki Core yuzu girer.
    # - Paralel duvarlarin serbest uclari (free-end), native end-cap
    #   Reference'i uzerinden AYNI Core zincirine eklenir.
    # Boylece dis duvar Core kalinligi + net mahal + ic duvar Core
    # kalinligi + koridor + ... tek linear dimension olur.
    #
    # NOT: full_finish_chain() fonksiyonu topoloji (dis sinirlar,
    # scan band, serbest uc adaylari) icin kullanilmaya devam eder;
    # ama donen Finish yuz referanslari (chain["items"]) artik
    # dimensiyona islenmez. Sadece descriptor icindeki "walls" ve
    # "accepted_finish_endpoint_candidates" (serbest uc referanslari)
    # kullanilir; referans kaynagi tamamen Core boundary'e (core_faces)
    # cevrilir.

    # --------------------------------------------------------
    # B1. SOLDAN SAGA - DIKEY DUVARLAR
    # --------------------------------------------------------

    debug_print("B1 CORE BLOCK CALLED")
    finish_jobs_x = room_chain_jobs(
        room_chain_tracks_x
    )

    for y, room_track in finish_jobs_x:
        chain = full_finish_chain(
            "DIKEY",
            y,
            room_track
        )

        if chain is None:
            skipped_count += 1
            continue

        descriptor = chain["descriptor"]
        direction_rejected_parallel_wall_count += descriptor.get(
            "direction_rejected_parallel_wall_count",
            0
        )
        room_side_rejected_cut_wall_count += len(
            descriptor.get(
                "room_side_rejected_cut_wall_ids",
                []
            )
        )
        terminating_room_side_rejected_count += descriptor.get(
            "terminating_room_side_rejected_count",
            0
        )
        left_wall = chain["start_wall"]

        core_items = []
        core_raw_records = []

        for wall in descriptor["walls"]:
            wall_id = element_id_key(wall.Id)
            key = element_id_key(
                wall.WallType.Id
            )

            if key not in core_calibrations:
                continue

            faces = core_faces(
                wall,
                core_calibrations[key],
                "X"
            )

            # V6: ilk/son dis duvar dahil HER kesen duvarin iki Core yuzu.
            for face in faces:
                core_items.append(face)
                core_raw_records.append(
                    (
                        face[0],
                        face[1],
                        wall_id
                    )
                )

        # Paralel duvarlarin serbest uclari: ayni native end-cap
        # Reference'i (Finish/Core'dan bagimsiz, tek fiziksel yuz).
        for candidate in descriptor["accepted_finish_endpoint_candidates"]:
            core_items.append(
                (
                    candidate["coordinate"],
                    candidate["reference"]
                )
            )
            core_raw_records.append(
                (
                    candidate["coordinate"],
                    candidate["reference"],
                    candidate["wall_id"]
                )
            )

        room_opening_reference_count = 0
        partition_opening_reference_count = 0

        if room_track is not None:
            first_boundary_coordinate = wall_info(
                descriptor["first_exterior_boundary"]
            )["mid_x"]
            last_boundary_coordinate = wall_info(
                descriptor["last_exterior_boundary"]
            )["mid_x"]
            boundary_min = min(
                first_boundary_coordinate,
                last_boundary_coordinate
            )
            boundary_max = max(
                first_boundary_coordinate,
                last_boundary_coordinate
            )

            column_items = column_items_for_room_track(
                "X",
                room_track,
                boundary_min,
                boundary_max
            )

            for coordinate, reference, column_id in column_items:
                core_items.append(
                    (
                        coordinate,
                        reference
                    )
                )
                core_raw_records.append(
                    (
                        coordinate,
                        reference,
                        column_id
                    )
                )
                column_reference_count += 1

            core_only_items = clean_items(
                list(core_items)
            )

            for opening_item in room_track["opening_items"]:
                coordinate = opening_item["coordinate"]

                if (
                    coordinate < boundary_min - TOL
                    or coordinate > boundary_max + TOL
                ):
                    continue

                core_items.append(
                    (
                        coordinate,
                        opening_item["reference"]
                    )
                )
                core_raw_records.append(
                    (
                        coordinate,
                        opening_item["reference"],
                        opening_item["host_wall_id"]
                    )
                )
                room_opening_reference_count += 1

                if not opening_item["host_is_exterior"]:
                    partition_opening_reference_count += 1
        else:
            core_only_items = clean_items(
                list(core_items)
            )

        descriptor["room_opening_reference_count"] = (
            room_opening_reference_count
        )

        core_items = clean_items(core_items)
        content_signature = chain_reference_content_signature(
            core_items
        )

        if (
            room_track is None
            and content_signature
            in room_chain_reference_signatures_x
        ):
            debug_print(
                "DUPLICATE BASELINE CORE CHAIN SKIPPED | "
                "Direction: X | Scan: {:.6f}".format(y)
            )
            continue

        log_clean_items_diagnostic(
            "Core",
            descriptor,
            core_raw_records,
            core_items
        )

        if len(core_items) < 2:
            skipped_count += 1
            continue

        signature = (
            descriptor["direction"],
            round(descriptor["scan_coordinate"], 4),
            tuple(descriptor["wall_ids"]),
            chain_signature(core_items)
        )

        if signature in core_signatures:
            continue

        z = wall_info(left_wall)["p0"].Z
        main_line_coordinate = y

        if room_opening_reference_count == 0:
            total_coordinate = first_secondary_coordinate(
                room_track
            )

            if total_coordinate is not None:
                main_line_coordinate = total_coordinate

        line = DB.Line.CreateBound(
            DB.XYZ(
                core_items[0][0],
                main_line_coordinate,
                z
            ),
            DB.XYZ(
                core_items[-1][0],
                main_line_coordinate,
                z
            )
        )

        main_visual_duplicate = chain_is_near_visual_duplicate(
            created_chain_visual_registry_x,
            core_items,
            main_line_coordinate
        )

        main_chain_kind = (
            "DETAIL"
            if room_opening_reference_count > 0
            else "TOTAL"
        )

        room_topology_key = room_topology_chain_key(
            descriptor,
            core_items,
            main_chain_kind
        )
        room_topology_duplicate = (
            room_topology_key is not None
            and room_topology_key in created_room_topology_chains
        )
        geometry_coverage_duplicate = False
        smart_preselection_duplicate = (
            (
                id(room_track),
                "MAIN"
            )
            not in smart_allowed_x
        )

        if (
            main_visual_duplicate
            or room_topology_duplicate
            or geometry_coverage_duplicate
            or smart_preselection_duplicate
        ):
            if (
                room_topology_duplicate
                or geometry_coverage_duplicate
            ):
                duplicate_room_chain_count += 1

            debug_print(
                "DUPLICATE CONTINUOUS CORE CHAIN SKIPPED | "
                "Direction: X | Scan: {:.6f}".format(y)
            )
        else:
            try:
                (
                    dimension,
                    refs,
                    core_items,
                    removed_zero_references
                ) = create_dimension_without_zero_segments(
                    line,
                    core_items
                )
                zero_segment_reference_removal_count += (
                    removed_zero_references
                )

                if dimension is None:
                    raise Exception(
                        "Zero segment cleanup left fewer than two references."
                    )

                signature = (
                    descriptor["direction"],
                    round(descriptor["scan_coordinate"], 4),
                    tuple(descriptor["wall_ids"]),
                    chain_signature(core_items)
                )
                content_signature = chain_reference_content_signature(
                    core_items
                )
                room_topology_key = room_topology_chain_key(
                    descriptor,
                    core_items,
                    main_chain_kind
                )
                log_dimension_segment_diagnostic(
                    "Core X",
                    dimension,
                    refs
                )
                core_signatures.add(signature)
                register_chain_visual_signature(
                    created_chain_visual_registry_x,
                    core_items,
                    main_line_coordinate
                )

                if room_topology_key is not None:
                    created_room_topology_chains.add(
                        room_topology_key
                    )

                core_chain_count += 1

                if room_opening_reference_count > 0:
                    opening_chain_count += 1

                if room_track is not None:
                    room_chain_reference_signatures_x.add(
                        content_signature
                    )

                shared_chain_descriptors_x.append(
                    descriptor
                )
                diagnostic_finish_scans_x.append(
                    main_line_coordinate
                )
                diagnostic_core_scans_x.append(
                    main_line_coordinate
                )

            except:
                skipped_count += 1

        if (
            room_track is not None
            and room_opening_reference_count > 0
            and len(core_only_items) >= 2
        ):
            for secondary_y in [
                first_secondary_coordinate(room_track)
            ]:
                if secondary_y is None:
                    continue

                if (
                    (
                        id(room_track),
                        "SECONDARY"
                    )
                    not in smart_allowed_x
                ):
                    continue

                no_opening_signature = (
                    descriptor["direction"],
                    round(secondary_y, 4),
                    tuple(descriptor["wall_ids"]),
                    chain_signature(core_only_items)
                )

                if no_opening_signature in core_signatures:
                    continue

                no_opening_topology_key = room_topology_chain_key(
                    descriptor,
                    core_only_items,
                    "TOTAL"
                )
                no_opening_geometry_duplicate = False

                if (
                    (
                        no_opening_topology_key is not None
                        and no_opening_topology_key
                        in created_room_topology_chains
                    )
                    or no_opening_geometry_duplicate
                ):
                    duplicate_room_chain_count += 1
                    continue

                if chain_is_near_visual_duplicate(
                    created_chain_visual_registry_x,
                    core_only_items,
                    secondary_y
                ):
                    debug_print(
                        "DUPLICATE CONTINUOUS CORE CHAIN SKIPPED | "
                        "Direction: X | Scan: {:.6f} | "
                        "Variant: NO OPENING".format(
                            secondary_y
                        )
                    )
                    continue

                no_opening_line = DB.Line.CreateBound(
                    DB.XYZ(
                        core_only_items[0][0],
                        secondary_y,
                        z
                    ),
                    DB.XYZ(
                        core_only_items[-1][0],
                        secondary_y,
                        z
                    )
                )

                try:
                    (
                        no_opening_dimension,
                        no_opening_refs,
                        core_only_items,
                        removed_zero_references
                    ) = create_dimension_without_zero_segments(
                        no_opening_line,
                        core_only_items
                    )
                    zero_segment_reference_removal_count += (
                        removed_zero_references
                    )

                    if no_opening_dimension is None:
                        raise Exception(
                            "Zero segment cleanup left fewer than two references."
                        )

                    no_opening_signature = (
                        descriptor["direction"],
                        round(secondary_y, 4),
                        tuple(descriptor["wall_ids"]),
                        chain_signature(core_only_items)
                    )
                    no_opening_topology_key = room_topology_chain_key(
                        descriptor,
                        core_only_items,
                        "TOTAL"
                    )
                    log_dimension_segment_diagnostic(
                        "Core X - No Opening",
                        no_opening_dimension,
                        no_opening_refs
                    )
                    core_signatures.add(
                        no_opening_signature
                    )
                    room_chain_reference_signatures_x.add(
                        chain_reference_content_signature(
                            core_only_items
                        )
                    )
                    register_chain_visual_signature(
                        created_chain_visual_registry_x,
                        core_only_items,
                        secondary_y
                    )
                    if no_opening_topology_key is not None:
                        created_room_topology_chains.add(
                            no_opening_topology_key
                        )
                    no_opening_chain_count += 1
                    core_chain_count += 1
                except:
                    skipped_count += 1


    # --------------------------------------------------------
    # B2. ALTTAN USTE - YATAY DUVARLAR
    # --------------------------------------------------------

    debug_print("B2 CORE BLOCK CALLED")
    finish_jobs_y = room_chain_jobs(
        room_chain_tracks_y
    )

    for x, room_track in finish_jobs_y:
        chain = full_finish_chain(
            "YATAY",
            x,
            room_track
        )

        if chain is None:
            skipped_count += 1
            continue

        descriptor = chain["descriptor"]
        direction_rejected_parallel_wall_count += descriptor.get(
            "direction_rejected_parallel_wall_count",
            0
        )
        room_side_rejected_cut_wall_count += len(
            descriptor.get(
                "room_side_rejected_cut_wall_ids",
                []
            )
        )
        terminating_room_side_rejected_count += descriptor.get(
            "terminating_room_side_rejected_count",
            0
        )
        bottom_wall = chain["start_wall"]

        core_items = []
        core_raw_records = []

        for wall in descriptor["walls"]:
            wall_id = element_id_key(wall.Id)
            key = element_id_key(
                wall.WallType.Id
            )

            if key not in core_calibrations:
                continue

            faces = core_faces(
                wall,
                core_calibrations[key],
                "Y"
            )

            for face in faces:
                core_items.append(face)
                core_raw_records.append(
                    (
                        face[0],
                        face[1],
                        wall_id
                    )
                )

        for candidate in descriptor["accepted_finish_endpoint_candidates"]:
            core_items.append(
                (
                    candidate["coordinate"],
                    candidate["reference"]
                )
            )
            core_raw_records.append(
                (
                    candidate["coordinate"],
                    candidate["reference"],
                    candidate["wall_id"]
                )
            )

        room_opening_reference_count = 0
        partition_opening_reference_count = 0

        if room_track is not None:
            first_boundary_coordinate = wall_info(
                descriptor["first_exterior_boundary"]
            )["mid_y"]
            last_boundary_coordinate = wall_info(
                descriptor["last_exterior_boundary"]
            )["mid_y"]
            boundary_min = min(
                first_boundary_coordinate,
                last_boundary_coordinate
            )
            boundary_max = max(
                first_boundary_coordinate,
                last_boundary_coordinate
            )

            column_items = column_items_for_room_track(
                "Y",
                room_track,
                boundary_min,
                boundary_max
            )

            for coordinate, reference, column_id in column_items:
                core_items.append(
                    (
                        coordinate,
                        reference
                    )
                )
                core_raw_records.append(
                    (
                        coordinate,
                        reference,
                        column_id
                    )
                )
                column_reference_count += 1

            core_only_items = clean_items(
                list(core_items)
            )

            for opening_item in room_track["opening_items"]:
                coordinate = opening_item["coordinate"]

                if (
                    coordinate < boundary_min - TOL
                    or coordinate > boundary_max + TOL
                ):
                    continue

                core_items.append(
                    (
                        coordinate,
                        opening_item["reference"]
                    )
                )
                core_raw_records.append(
                    (
                        coordinate,
                        opening_item["reference"],
                        opening_item["host_wall_id"]
                    )
                )
                room_opening_reference_count += 1

                if not opening_item["host_is_exterior"]:
                    partition_opening_reference_count += 1
        else:
            core_only_items = clean_items(
                list(core_items)
            )

        descriptor["room_opening_reference_count"] = (
            room_opening_reference_count
        )

        core_items = clean_items(core_items)
        content_signature = chain_reference_content_signature(
            core_items
        )

        if (
            room_track is None
            and content_signature
            in room_chain_reference_signatures_y
        ):
            debug_print(
                "DUPLICATE BASELINE CORE CHAIN SKIPPED | "
                "Direction: Y | Scan: {:.6f}".format(x)
            )
            continue

        log_clean_items_diagnostic(
            "Core",
            descriptor,
            core_raw_records,
            core_items
        )

        if len(core_items) < 2:
            skipped_count += 1
            continue

        signature = (
            descriptor["direction"],
            round(descriptor["scan_coordinate"], 4),
            tuple(descriptor["wall_ids"]),
            chain_signature(core_items)
        )

        if signature in core_signatures:
            continue

        z = wall_info(bottom_wall)["p0"].Z
        main_line_coordinate = x

        if room_opening_reference_count == 0:
            total_coordinate = first_secondary_coordinate(
                room_track
            )

            if total_coordinate is not None:
                main_line_coordinate = total_coordinate

        line = DB.Line.CreateBound(
            DB.XYZ(
                main_line_coordinate,
                core_items[0][0],
                z
            ),
            DB.XYZ(
                main_line_coordinate,
                core_items[-1][0],
                z
            )
        )

        main_visual_duplicate = chain_is_near_visual_duplicate(
            created_chain_visual_registry_y,
            core_items,
            main_line_coordinate
        )

        main_chain_kind = (
            "DETAIL"
            if room_opening_reference_count > 0
            else "TOTAL"
        )

        room_topology_key = room_topology_chain_key(
            descriptor,
            core_items,
            main_chain_kind
        )
        room_topology_duplicate = (
            room_topology_key is not None
            and room_topology_key in created_room_topology_chains
        )
        geometry_coverage_duplicate = False
        smart_preselection_duplicate = (
            (
                id(room_track),
                "MAIN"
            )
            not in smart_allowed_y
        )

        if (
            main_visual_duplicate
            or room_topology_duplicate
            or geometry_coverage_duplicate
            or smart_preselection_duplicate
        ):
            if (
                room_topology_duplicate
                or geometry_coverage_duplicate
            ):
                duplicate_room_chain_count += 1

            debug_print(
                "DUPLICATE CONTINUOUS CORE CHAIN SKIPPED | "
                "Direction: Y | Scan: {:.6f}".format(x)
            )
        else:
            try:
                (
                    dimension,
                    refs,
                    core_items,
                    removed_zero_references
                ) = create_dimension_without_zero_segments(
                    line,
                    core_items
                )
                zero_segment_reference_removal_count += (
                    removed_zero_references
                )

                if dimension is None:
                    raise Exception(
                        "Zero segment cleanup left fewer than two references."
                    )

                signature = (
                    descriptor["direction"],
                    round(descriptor["scan_coordinate"], 4),
                    tuple(descriptor["wall_ids"]),
                    chain_signature(core_items)
                )
                content_signature = chain_reference_content_signature(
                    core_items
                )
                room_topology_key = room_topology_chain_key(
                    descriptor,
                    core_items,
                    main_chain_kind
                )
                log_dimension_segment_diagnostic(
                    "Core Y",
                    dimension,
                    refs
                )
                core_signatures.add(signature)
                register_chain_visual_signature(
                    created_chain_visual_registry_y,
                    core_items,
                    main_line_coordinate
                )

                if room_topology_key is not None:
                    created_room_topology_chains.add(
                        room_topology_key
                    )

                core_chain_count += 1

                if room_opening_reference_count > 0:
                    opening_chain_count += 1

                if room_track is not None:
                    room_chain_reference_signatures_y.add(
                        content_signature
                    )

                shared_chain_descriptors_y.append(
                    descriptor
                )
                diagnostic_finish_scans_y.append(
                    main_line_coordinate
                )
                diagnostic_core_scans_y.append(
                    main_line_coordinate
                )

            except:
                skipped_count += 1

        if (
            room_track is not None
            and room_opening_reference_count > 0
            and len(core_only_items) >= 2
        ):
            for secondary_x in [
                first_secondary_coordinate(room_track)
            ]:
                if secondary_x is None:
                    continue

                if (
                    (
                        id(room_track),
                        "SECONDARY"
                    )
                    not in smart_allowed_y
                ):
                    continue

                no_opening_signature = (
                    descriptor["direction"],
                    round(secondary_x, 4),
                    tuple(descriptor["wall_ids"]),
                    chain_signature(core_only_items)
                )

                if no_opening_signature in core_signatures:
                    continue

                no_opening_topology_key = room_topology_chain_key(
                    descriptor,
                    core_only_items,
                    "TOTAL"
                )
                no_opening_geometry_duplicate = False

                if (
                    (
                        no_opening_topology_key is not None
                        and no_opening_topology_key
                        in created_room_topology_chains
                    )
                    or no_opening_geometry_duplicate
                ):
                    duplicate_room_chain_count += 1
                    continue

                if chain_is_near_visual_duplicate(
                    created_chain_visual_registry_y,
                    core_only_items,
                    secondary_x
                ):
                    debug_print(
                        "DUPLICATE CONTINUOUS CORE CHAIN SKIPPED | "
                        "Direction: Y | Scan: {:.6f} | "
                        "Variant: NO OPENING".format(
                            secondary_x
                        )
                    )
                    continue

                no_opening_line = DB.Line.CreateBound(
                    DB.XYZ(
                        secondary_x,
                        core_only_items[0][0],
                        z
                    ),
                    DB.XYZ(
                        secondary_x,
                        core_only_items[-1][0],
                        z
                    )
                )

                try:
                    (
                        no_opening_dimension,
                        no_opening_refs,
                        core_only_items,
                        removed_zero_references
                    ) = create_dimension_without_zero_segments(
                        no_opening_line,
                        core_only_items
                    )
                    zero_segment_reference_removal_count += (
                        removed_zero_references
                    )

                    if no_opening_dimension is None:
                        raise Exception(
                            "Zero segment cleanup left fewer than two references."
                        )

                    no_opening_signature = (
                        descriptor["direction"],
                        round(secondary_x, 4),
                        tuple(descriptor["wall_ids"]),
                        chain_signature(core_only_items)
                    )
                    no_opening_topology_key = room_topology_chain_key(
                        descriptor,
                        core_only_items,
                        "TOTAL"
                    )
                    log_dimension_segment_diagnostic(
                        "Core Y - No Opening",
                        no_opening_dimension,
                        no_opening_refs
                    )
                    core_signatures.add(
                        no_opening_signature
                    )
                    room_chain_reference_signatures_y.add(
                        chain_reference_content_signature(
                            core_only_items
                        )
                    )
                    register_chain_visual_signature(
                        created_chain_visual_registry_y,
                        core_only_items,
                        secondary_x
                    )
                    if no_opening_topology_key is not None:
                        created_room_topology_chains.add(
                            no_opening_topology_key
                        )
                    no_opening_chain_count += 1
                    core_chain_count += 1
                except:
                    skipped_count += 1



def log_wall_coverage_diagnostic():
    if not DEBUG:
        return

    debug_print("=== WALL CONTINUOUS CHAIN COVERAGE DIAGNOSTIC ===")

    ordered_walls = sorted(
        basic_straight_walls,
        key=lambda wall: element_id_key(wall.Id)
    )

    for wall in ordered_walls:
        info = wall_info(wall)
        wall_id = element_id_key(wall.Id)
        p0 = info["p0"]
        p1 = info["p1"]

        if info["yon"] == "DIKEY":
            descriptor_direction = "X"
            descriptors = shared_chain_descriptors_x
            extent_axis = "Y"
            extent_min = min(p0.Y, p1.Y)
            extent_max = max(p0.Y, p1.Y)
            wall_axis_coord = info["mid_x"]

            def scan_intersects(descriptor):
                return crosses_y(
                    wall,
                    descriptor["scan_coordinate"]
                )

            def boundary_coord(boundary_wall):
                return wall_info(boundary_wall)["mid_x"]

        else:
            descriptor_direction = "Y"
            descriptors = shared_chain_descriptors_y
            extent_axis = "X"
            extent_min = min(p0.X, p1.X)
            extent_max = max(p0.X, p1.X)
            wall_axis_coord = info["mid_y"]

            def scan_intersects(descriptor):
                return crosses_x(
                    wall,
                    descriptor["scan_coordinate"]
                )

            def boundary_coord(boundary_wall):
                return wall_info(boundary_wall)["mid_y"]

        covering_descriptors = [
            descriptor
            for descriptor in descriptors
            if wall_id in descriptor["wall_ids"]
        ]
        intersecting_descriptors = [
            descriptor
            for descriptor in descriptors
            if scan_intersects(descriptor)
        ]

        debug_print("--- WALL COVERAGE ---")
        debug_print("Wall ID: {}".format(wall.Id.ToString()))
        debug_print("Wall direction: {}".format(info["yon"]))
        debug_print(
            "Wall extents | P0: ({:.6f}, {:.6f}, {:.6f}) | "
            "P1: ({:.6f}, {:.6f}, {:.6f})".format(
                p0.X,
                p0.Y,
                p0.Z,
                p1.X,
                p1.Y,
                p1.Z
            )
        )
        debug_print(
            "Perpendicular descriptor direction: {}".format(
                descriptor_direction
            )
        )
        debug_print(
            "Available scan coordinates: {}".format(
                ", ".join([
                    "{:.6f}".format(
                        descriptor["scan_coordinate"]
                    )
                    for descriptor in descriptors
                ])
            )
        )
        debug_print(
            "Covering descriptor scan coordinates: {}".format(
                ", ".join([
                    "{:.6f}".format(
                        descriptor["scan_coordinate"]
                    )
                    for descriptor in covering_descriptors
                ])
            )
        )

        if len(covering_descriptors) > 0:
            debug_print("Wall covered by continuous chain: YES")
            continue

        debug_print("Wall covered by continuous chain: NO")
        debug_print(
            "WALL {} NEVER COVERED BY ANY CONTINUOUS CHAIN".format(
                wall.Id.ToString()
            )
        )

        if len(descriptors) == 0:
            debug_print(
                "Coverage reason: No Direction {} Finish chain "
                "descriptor exists.".format(
                    descriptor_direction
                )
            )
            continue

        if len(intersecting_descriptors) == 0:
            debug_print(
                "Coverage reason: No Direction {} scan coordinate "
                "intersects wall {} extent [{:.6f}, {:.6f}].".format(
                    descriptor_direction,
                    extent_axis,
                    extent_min,
                    extent_max
                )
            )
            continue

        for descriptor in intersecting_descriptors:
            first_wall = descriptor["first_exterior_boundary"]
            last_wall = descriptor["last_exterior_boundary"]
            first_coord = boundary_coord(first_wall)
            last_coord = boundary_coord(last_wall)
            boundary_min = min(first_coord, last_coord)
            boundary_max = max(first_coord, last_coord)

            if (
                wall_axis_coord < boundary_min - TOL
                or wall_axis_coord > boundary_max + TOL
            ):
                debug_print(
                    "Coverage reason: Scan {:.6f} intersects wall "
                    "extent, but wall axis coordinate {:.6f} is outside "
                    "exterior boundary interval [{:.6f}, {:.6f}] "
                    "(first Wall {}, last Wall {}).".format(
                        descriptor["scan_coordinate"],
                        wall_axis_coord,
                        boundary_min,
                        boundary_max,
                        first_wall.Id.ToString(),
                        last_wall.Id.ToString()
                    )
                )
            else:
                debug_print(
                    "Coverage reason: Scan {:.6f} intersects wall "
                    "extent and wall lies inside exterior boundaries, "
                    "but Wall ID is absent from descriptor.".format(
                        descriptor["scan_coordinate"]
                    )
                )

    debug_print("=== END WALL CONTINUOUS CHAIN COVERAGE DIAGNOSTIC ===")


log_wall_coverage_diagnostic()


def diagnostic_scan_exists(values, scan_value):
    for value in values:
        if abs(value - scan_value) <= TOL:
            return True

    return False


def diagnostic_unique_scans(values):
    result = []

    for value in sorted(values):
        if (
            len(result) == 0
            or abs(value - result[-1]) > TOL
        ):
            result.append(value)

    return result


def diagnostic_scan_text(values):
    return ", ".join([
        "{:.6f}".format(value)
        for value in diagnostic_unique_scans(values)
    ])


def log_core_scan_diagnostic(
    direction,
    scan_value,
    finish_scans,
    core_used_scans,
    core_created_scans
):
    if not DEBUG:
        return

    finish_exists = diagnostic_scan_exists(
        finish_scans,
        scan_value
    )
    core_scan_used = diagnostic_scan_exists(
        core_used_scans,
        scan_value
    )
    core_exists = diagnostic_scan_exists(
        core_created_scans,
        scan_value
    )

    cut_walls = []

    for wall in basic_straight_walls:
        info = wall_info(wall)

        if direction == "X":
            if info["yon"] != "DIKEY":
                continue

            if not crosses_y(wall, scan_value):
                continue

            wall_coord = info["mid_x"]
        else:
            if info["yon"] != "YATAY":
                continue

            if not crosses_x(wall, scan_value):
                continue

            wall_coord = info["mid_y"]

        cut_walls.append((wall_coord, wall))

    cut_walls.sort(key=lambda item: item[0])

    debug_print("=== CORE CHAIN SCAN DIAGNOSTIC ===")
    debug_print("Direction: {}".format(direction))
    debug_print("Scan coordinate: {:.6f}".format(scan_value))
    debug_print(
        "Finish chain exists: {}".format(
            "YES" if finish_exists else "NO"
        )
    )
    debug_print(
        "Core scan used: {}".format(
            "YES" if core_scan_used else "NO"
        )
    )
    debug_print(
        "Core chain exists: {}".format(
            "YES" if core_exists else "NO"
        )
    )
    debug_print(
        "Intersecting Wall IDs: {}".format(
            ", ".join([
                wall.Id.ToString()
                for wall_coord, wall in cut_walls
            ])
        )
    )

    for wall_coord, wall in cut_walls:
        key = element_id_key(wall.WallType.Id)
        faces = []

        if key in core_calibrations:
            try:
                faces = core_faces(
                    wall,
                    core_calibrations[key],
                    direction
                )
            except:
                faces = []

        coordinates = [
            face[0]
            for face in faces
        ]

        debug_print(
            "Wall {} | Core reference count: {} | "
            "Expected Core reference count: 2 | "
            "Core reference coordinates: [{}]".format(
                wall.Id.ToString(),
                len(faces),
                ", ".join([
                    "{:.6f}".format(coord)
                    for coord in coordinates
                ])
            )
        )

        if len(faces) == 1:
            debug_print(
                "WALL {} LOST CORE FACE".format(
                    wall.Id.ToString()
                )
            )

    if finish_exists and not core_exists:
        debug_print("CORE CHAIN MISSING FOR FINISH SCAN")

    debug_print("=== END CORE CHAIN SCAN DIAGNOSTIC ===")


diagnostic_core_used_scans_x = [
    descriptor["scan_coordinate"]
    for descriptor in shared_chain_descriptors_x
]
diagnostic_core_used_scans_y = [
    descriptor["scan_coordinate"]
    for descriptor in shared_chain_descriptors_y
]

debug_print("=== FINISH / CORE SCAN COORDINATE COMPARISON ===")
debug_print(
    "Direction X | Finish scan coordinates: {}".format(
        diagnostic_scan_text(diagnostic_finish_scans_x)
    )
)
debug_print(
    "Direction X | Core-used scan coordinates: {}".format(
        diagnostic_scan_text(diagnostic_core_used_scans_x)
    )
)
debug_print(
    "Direction Y | Finish scan coordinates: {}".format(
        diagnostic_scan_text(diagnostic_finish_scans_y)
    )
)
debug_print(
    "Direction Y | Core-used scan coordinates: {}".format(
        diagnostic_scan_text(diagnostic_core_used_scans_y)
    )
)

diagnostic_all_scans_x = diagnostic_unique_scans(
    list(diagnostic_finish_scans_x)
    + list(diagnostic_core_used_scans_x)
)
diagnostic_all_scans_y = diagnostic_unique_scans(
    list(diagnostic_finish_scans_y)
    + list(diagnostic_core_used_scans_y)
)

for diagnostic_scan in diagnostic_all_scans_x:
    log_core_scan_diagnostic(
        "X",
        diagnostic_scan,
        diagnostic_finish_scans_x,
        diagnostic_core_used_scans_x,
        diagnostic_core_scans_x
    )

for diagnostic_scan in diagnostic_all_scans_y:
    log_core_scan_diagnostic(
        "Y",
        diagnostic_scan,
        diagnostic_finish_scans_y,
        diagnostic_core_used_scans_y,
        diagnostic_core_scans_y
    )


# ============================================================
# 19. SONUC
# ============================================================

forms.alert(
    "INTERIOR DIMENSION V19 - COK YUKSEKLIKLI DUVAR TESTI\n"
    "Olculer modelde olusturuldu.\n\n"
    "Yuz yonu filtresi: AKTIF\n"
    "5 mm alti sifir aralik filtresi: AKTIF\n"
    "Kapi/pencere icin cok yukseklikli duvar probu: AKTIF\n"
    "40 cm bosluklu Core zinciri: {}\n"
    "80 cm bosluksuz Core zinciri: {}\n"
    "Toplam Core zinciri: {}\n"
    "Gercek duvar boslugu bulunan kapi/pencere: {}\n"
    "Duvar bosluk yuzu bulunamayan: {}\n"
    "Bulunamayan kapi/pencere ID: {}\n"
    "Testte gecersiz bulunan bosluk: {}\n"
    "Gecersiz kapi/pencere ID: {}\n"
    "Zincire eklenen kolon yuz referansi: {}\n"
    "Secilen ic duvar Room-yuzu: {}\n"
    "Farkli Room ile birlestirilen iz (beklenen 0): {}\n"
    "Ters yuzden elenen paralel duvar adayi: {}\n"
    "Room tarafina girmeden elenen dik duvar: {}\n"
    "Join ucundan gelip gorunuste kesmeyen duvar: {}\n"
    "Gorunur geometriyle sinanan duvar izi: {}\n"
    "Bosluk ustunden zincire geri alinan duvar izi: {}\n"
    "Eksen kontrolune dusen duvar izi: {}\n"
    "Revit testinde silinen sifir aralikli referans: {}\n"
    "Olusturulmadan elenen aday zincir: {}\n"
    "Mahalde engellenen tekrar zinciri: {}\n"
    "Testi gecen kolon yonu: {}\n"
    "Gecersiz kolon yonu: {}\n"
    "Core taninan Wall Type: {}\n"
    "Atlanan: {}".format(
        opening_chain_count,
        no_opening_chain_count,
        core_chain_count,
        len(OPENING_WALL_FACE_SUCCESS_IDS),
        len(OPENING_WALL_FACE_MISSING_IDS),
        (
            ", ".join([
                str(item)
                for item in sorted(
                    OPENING_WALL_FACE_MISSING_IDS
                )
            ])
            if len(OPENING_WALL_FACE_MISSING_IDS) > 0
            else "YOK"
        ),
        len(OPENING_WALL_FACE_INVALID_IDS),
        (
            ", ".join([
                str(item)
                for item in sorted(
                    OPENING_WALL_FACE_INVALID_IDS
                )
            ])
            if len(OPENING_WALL_FACE_INVALID_IDS) > 0
            else "YOK"
        ),
        column_reference_count,
        len(selected_interior_surface_keys),
        sum([
            track.get("continued_room_count", 0)
            for track in (
                list(room_chain_tracks_x)
                + list(room_chain_tracks_y)
            )
        ]),
        direction_rejected_parallel_wall_count,
        room_side_rejected_cut_wall_count,
        terminating_room_side_rejected_count,
        len(WALL_VISIBLE_GEOMETRY_USED_KEYS),
        len(WALL_MULTI_HEIGHT_PROBE_RECOVERY_KEYS),
        len(WALL_VISIBLE_GEOMETRY_FALLBACK_KEYS),
        zero_segment_reference_removal_count,
        smart_preselection_rejected_count,
        duplicate_room_chain_count,
        len(COLUMN_FACE_SUCCESS_KEYS),
        len(COLUMN_FACE_INVALID_KEYS),
        len(core_calibrations),
        skipped_count
    )
)
