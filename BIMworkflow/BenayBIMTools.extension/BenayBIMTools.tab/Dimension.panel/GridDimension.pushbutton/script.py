# -*- coding: utf-8 -*-

from pyrevit import forms, revit, DB
from benay_integrity import verify_brand_integrity


__author__ = "Benay Kaner"
__copyright__ = "Copyright (c) 2026 Benay Kaner"

verify_brand_integrity()


__title__ = "Grid"
__doc__ = (
    "Aktif gorunumdeki duz yatay ve dusey gridleri; "
    "ardisik araliklar ve ilk-son toplam olcu olarak olculendirir."
)


doc = revit.doc
view = revit.active_view

TOL = 0.001
CHAIN_OFFSET = DB.UnitUtils.ConvertToInternalUnits(
    3.0,
    DB.UnitTypeId.Meters
)
OVERALL_OFFSET = DB.UnitUtils.ConvertToInternalUnits(
    4.0,
    DB.UnitTypeId.Meters
)


def element_id_key(element_id):
    try:
        return element_id.IntegerValue
    except:
        return element_id.Value


def exterior_wall_face_bounds():
    walls = DB.FilteredElementCollector(doc, view.Id)\
        .OfClass(DB.Wall)\
        .WhereElementIsNotElementType()\
        .ToElements()

    min_x = None
    max_x = None
    min_y = None
    max_y = None

    for wall in walls:
        try:
            wall_type = doc.GetElement(wall.GetTypeId())

            if wall_type.Function != DB.WallFunction.Exterior:
                continue

            curve = wall.Location.Curve

            if not isinstance(curve, DB.Line):
                continue

            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            dx = abs(p1.X - p0.X)
            dy = abs(p1.Y - p0.Y)
            half_width = wall.Width / 2.0

            if dy <= TOL and dx > TOL:
                center_y = (p0.Y + p1.Y) / 2.0
                face_min_y = center_y - half_width
                face_max_y = center_y + half_width

                if min_y is None or face_min_y < min_y:
                    min_y = face_min_y

                if max_y is None or face_max_y > max_y:
                    max_y = face_max_y

            elif dx <= TOL and dy > TOL:
                center_x = (p0.X + p1.X) / 2.0
                face_min_x = center_x - half_width
                face_max_x = center_x + half_width

                if min_x is None or face_min_x < min_x:
                    min_x = face_min_x

                if max_x is None or face_max_x > max_x:
                    max_x = face_max_x
        except:
            continue

    return {
        "min_x": min_x,
        "max_x": max_x,
        "min_y": min_y,
        "max_y": max_y
    }


def grid_view_line(grid):
    curves = []

    for extent_type in [
        DB.DatumExtentType.ViewSpecific,
        DB.DatumExtentType.Model
    ]:
        try:
            curves = list(
                grid.GetCurvesInView(
                    extent_type,
                    view
                )
            )
        except:
            curves = []

        if len(curves) > 0:
            break

    if len(curves) == 0:
        try:
            curves = [grid.Curve]
        except:
            curves = []

    linear_curves = [
        curve
        for curve in curves
        if isinstance(curve, DB.Line)
    ]

    if len(linear_curves) == 0:
        return None

    linear_curves.sort(
        key=lambda curve: curve.Length,
        reverse=True
    )
    return linear_curves[0]


def grid_data(grid):
    curve = grid_view_line(grid)

    if curve is None:
        return None

    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    dx = abs(p1.X - p0.X)
    dy = abs(p1.Y - p0.Y)

    if dx <= TOL and dy > TOL:
        direction = "VERTICAL"
        coordinate = (p0.X + p1.X) / 2.0
    elif dy <= TOL and dx > TOL:
        direction = "HORIZONTAL"
        coordinate = (p0.Y + p1.Y) / 2.0
    else:
        return None

    return {
        "grid": grid,
        "grid_id": element_id_key(grid.Id),
        "curve": curve,
        "p0": p0,
        "p1": p1,
        "direction": direction,
        "coordinate": coordinate
    }


def unique_grid_data(items):
    result = []

    for item in sorted(
        items,
        key=lambda data: (
            data["coordinate"],
            data["grid_id"]
        )
    ):
        duplicate = False

        for existing in result:
            if (
                abs(
                    existing["coordinate"]
                    - item["coordinate"]
                ) <= TOL
            ):
                duplicate = True
                break

        if not duplicate:
            result.append(item)

    return result


def grid_reference_array(items, overall_only):
    refs = DB.ReferenceArray()

    if overall_only:
        selected_items = [
            items[0],
            items[-1]
        ]
    else:
        selected_items = items

    for item in selected_items:
        refs.Append(
            DB.Reference(item["grid"])
        )

    return refs


def create_dimension(line, items, overall_only):
    refs = grid_reference_array(
        items,
        overall_only
    )

    if refs.Size < 2:
        return False

    try:
        doc.Create.NewDimension(
            view,
            line,
            refs
        )
        return True
    except:
        return False


grids = DB.FilteredElementCollector(doc, view.Id)\
    .OfClass(DB.Grid)\
    .WhereElementIsNotElementType()\
    .ToElements()

vertical_grids = []
horizontal_grids = []
all_points = []
skipped_grid_count = 0

for grid in grids:
    data = grid_data(grid)

    if data is None:
        skipped_grid_count += 1
        continue

    all_points.extend([
        data["p0"],
        data["p1"]
    ])

    if data["direction"] == "VERTICAL":
        vertical_grids.append(data)
    else:
        horizontal_grids.append(data)

vertical_grids = unique_grid_data(vertical_grids)
horizontal_grids = unique_grid_data(horizontal_grids)

if (
    len(vertical_grids) < 2
    and len(horizontal_grids) < 2
):
    forms.alert(
        "Aktif gorunumde olculendirilebilecek en az iki "
        "duz ve orthogonal Grid bulunamadi.",
        title="BenayBIMTools"
    )
else:
    wall_bounds = exterior_wall_face_bounds()
    min_x = wall_bounds["min_x"]
    max_x = wall_bounds["max_x"]
    min_y = wall_bounds["min_y"]
    max_y = wall_bounds["max_y"]
    z = all_points[0].Z

    missing_boundaries = []

    if (
        len(vertical_grids) >= 2
        and (min_y is None or max_y is None)
    ):
        missing_boundaries.append("ust/alt Exterior wall")

    if (
        len(horizontal_grids) >= 2
        and (min_x is None or max_x is None)
    ):
        missing_boundaries.append("sol/sag Exterior wall")

    if len(missing_boundaries) > 0:
        forms.alert(
            "Grid dimension konumu icin gerekli {} bulunamadi.".format(
                ", ".join(missing_boundaries)
            ),
            title="BenayBIMTools",
            exitscript=True
        )

    dimension_count = 0
    failed_count = 0

    with revit.Transaction("Grid Dimension"):
        if len(vertical_grids) >= 2:
            first_x = vertical_grids[0]["coordinate"]
            last_x = vertical_grids[-1]["coordinate"]

            vertical_lines = [
                (
                    DB.Line.CreateBound(
                        DB.XYZ(first_x, max_y + CHAIN_OFFSET, z),
                        DB.XYZ(last_x, max_y + CHAIN_OFFSET, z)
                    ),
                    False
                ),
                (
                    DB.Line.CreateBound(
                        DB.XYZ(first_x, max_y + OVERALL_OFFSET, z),
                        DB.XYZ(last_x, max_y + OVERALL_OFFSET, z)
                    ),
                    True
                ),
                (
                    DB.Line.CreateBound(
                        DB.XYZ(first_x, min_y - CHAIN_OFFSET, z),
                        DB.XYZ(last_x, min_y - CHAIN_OFFSET, z)
                    ),
                    False
                ),
                (
                    DB.Line.CreateBound(
                        DB.XYZ(first_x, min_y - OVERALL_OFFSET, z),
                        DB.XYZ(last_x, min_y - OVERALL_OFFSET, z)
                    ),
                    True
                )
            ]

            for line, overall_only in vertical_lines:
                if create_dimension(line, vertical_grids, overall_only):
                    dimension_count += 1
                else:
                    failed_count += 1

        if len(horizontal_grids) >= 2:
            first_y = horizontal_grids[0]["coordinate"]
            last_y = horizontal_grids[-1]["coordinate"]

            horizontal_lines = [
                (
                    DB.Line.CreateBound(
                        DB.XYZ(min_x - CHAIN_OFFSET, first_y, z),
                        DB.XYZ(min_x - CHAIN_OFFSET, last_y, z)
                    ),
                    False
                ),
                (
                    DB.Line.CreateBound(
                        DB.XYZ(min_x - OVERALL_OFFSET, first_y, z),
                        DB.XYZ(min_x - OVERALL_OFFSET, last_y, z)
                    ),
                    True
                ),
                (
                    DB.Line.CreateBound(
                        DB.XYZ(max_x + CHAIN_OFFSET, first_y, z),
                        DB.XYZ(max_x + CHAIN_OFFSET, last_y, z)
                    ),
                    False
                ),
                (
                    DB.Line.CreateBound(
                        DB.XYZ(max_x + OVERALL_OFFSET, first_y, z),
                        DB.XYZ(max_x + OVERALL_OFFSET, last_y, z)
                    ),
                    True
                )
            ]

            for line, overall_only in horizontal_lines:
                if create_dimension(line, horizontal_grids, overall_only):
                    dimension_count += 1
                else:
                    failed_count += 1

    forms.alert(
        "{} Grid dimension olusturuldu.\n"
        "Atlanan egik/yay Grid: {}\n"
        "Olusturulamayan dimension: {}".format(
            dimension_count,
            skipped_grid_count,
            failed_count
        ),
        title="BenayBIMTools"
    )
