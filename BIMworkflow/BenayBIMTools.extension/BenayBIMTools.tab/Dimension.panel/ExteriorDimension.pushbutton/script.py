# -*- coding: utf-8 -*-

from pyrevit import forms, revit, DB, script
from benay_integrity import verify_brand_integrity


__author__ = "Benay Kaner"
__copyright__ = "Copyright (c) 2026 Benay Kaner"

verify_brand_integrity()

doc = revit.doc
view = revit.active_view
output = script.get_output()
DIAGNOSTIC_ENABLED = False


# --------------------------------------------------
# P0 DIAGNOSTIC
# --------------------------------------------------

diagnostic_events = {}
diagnostic_success_count = 0
diagnostic_summary_printed = False
outside_active_view_details = []
outside_active_view_opening_ids = set()
host_mismatch_opening_ids = set()
facade_wall_diagnostics = []
facade_opening_diagnostics = []
host_mismatch_details = []


def element_id_text(element):
    try:
        return element.Id.ToString()
    except:
        return "-"


def element_name(element):
    try:
        return element.Name
    except:
        return "-"


def element_type_data(element):
    family_name = "-"
    type_name = "-"

    try:
        element_type = doc.GetElement(element.GetTypeId())
    except:
        element_type = None

    if element_type is not None:
        type_name = element_name(element_type)

        try:
            family_name = element_type.FamilyName
        except:
            try:
                family_name = element_type.Family.Name
            except:
                pass

    return family_name, type_name


def view_phase_text():
    try:
        parameter = view.get_Parameter(
            DB.BuiltInParameter.VIEW_PHASE
        )
        phase = doc.GetElement(parameter.AsElementId())
        return element_name(phase)
    except:
        return "-"


def parameter_element_text(element, built_in_parameter):
    try:
        parameter = element.get_Parameter(built_in_parameter)

        if parameter is None:
            return "-"

        referenced = doc.GetElement(parameter.AsElementId())

        if referenced is None:
            return "-"

        return element_name(referenced)
    except:
        return "-"


def created_phase_text(element):
    return parameter_element_text(
        element,
        DB.BuiltInParameter.PHASE_CREATED
    )


def demolished_phase_text(element):
    return parameter_element_text(
        element,
        DB.BuiltInParameter.PHASE_DEMOLISHED
    )


def view_phase_filter_text():
    return parameter_element_text(
        view,
        DB.BuiltInParameter.VIEW_PHASE_FILTER
    )


def category_text(element):
    try:
        return element.Category.Name
    except:
        return "-"


def host_element(element):
    try:
        return element.Host
    except:
        return None


def active_view_design_option_text():
    parameter_names = [
        "VIEWER_OPTION_VISIBILITY",
        "VIEW_DESIGN_OPTION_VISIBILITY"
    ]

    for parameter_name in parameter_names:
        try:
            built_in_parameter = getattr(
                DB.BuiltInParameter,
                parameter_name
            )
            parameter = view.get_Parameter(built_in_parameter)

            if parameter is None:
                continue

            option = doc.GetElement(parameter.AsElementId())

            if option is not None:
                return element_name(option)

            value = parameter.AsValueString()

            if value:
                return value
        except:
            pass

    for parameter_name in [
        "Visible In Option",
        "Design Option"
    ]:
        try:
            parameter = view.LookupParameter(parameter_name)

            if parameter is None:
                continue

            option = doc.GetElement(parameter.AsElementId())

            if option is not None:
                return element_name(option)

            value = parameter.AsValueString()

            if value:
                return value
        except:
            pass

    return "Automatic / API unavailable"


def phase_index(phase_name):
    if phase_name == "-":
        return None

    try:
        phases = list(doc.Phases)
    except:
        return None

    for index, phase in enumerate(phases):
        if element_name(phase) == phase_name:
            return index

    return None


def phase_mismatch_confirmed(element):
    created_index = phase_index(created_phase_text(element))
    demolished_index = phase_index(demolished_phase_text(element))
    active_index = phase_index(view_phase_text())

    if active_index is None:
        return False

    if created_index is not None and created_index > active_index:
        return True

    # Demolished in an earlier phase is definitively absent. If demolition
    # equals the view phase, Phase Filter decides and is not guessed here.
    if demolished_index is not None and demolished_index < active_index:
        return True

    return False


def design_option_mismatch_confirmed(element):
    element_option = design_option_text(element)
    visible_option = active_view_design_option_text()
    unknown_values = [
        "Main Model",
        "Automatic / API unavailable",
        "Automatic",
        "-"
    ]

    return (
        element_option not in unknown_values
        and visible_option not in unknown_values
        and element_option != visible_option
    )


def bounding_box_in_active_view(element):
    try:
        return element.get_BoundingBox(view) is not None
    except:
        return False


def parameter_value_text(element, built_in_names):
    for built_in_name in built_in_names:
        try:
            built_in_parameter = getattr(
                DB.BuiltInParameter,
                built_in_name
            )
            parameter = element.get_Parameter(built_in_parameter)

            if parameter is None:
                continue

            try:
                referenced = doc.GetElement(parameter.AsElementId())

                if referenced is not None:
                    return element_name(referenced)
            except:
                pass

            try:
                value = parameter.AsValueString()

                if value:
                    return value
            except:
                pass

            try:
                value = parameter.AsString()

                if value:
                    return value
            except:
                pass
        except:
            pass

    return "-"


def opening_level_text(opening):
    return parameter_value_text(
        opening,
        [
            "FAMILY_LEVEL_PARAM",
            "INSTANCE_REFERENCE_LEVEL_PARAM",
            "SCHEDULE_LEVEL_PARAM"
        ]
    )


def wall_base_constraint_text(wall):
    return parameter_value_text(
        wall,
        ["WALL_BASE_CONSTRAINT"]
    )


def wall_top_constraint_text(wall):
    return parameter_value_text(
        wall,
        ["WALL_HEIGHT_TYPE"]
    )


def family_reference_count(opening, reference_type):
    try:
        references = opening.GetReferences(reference_type)

        if references is None:
            return 0

        return len(references)
    except Exception as error:
        return "ERROR: {}".format(str(error))


def element_class_text(element):
    try:
        return element.GetType().Name
    except:
        return type(element).__name__


def element_descriptor(element):
    if element is None:
        return "MISSING ELEMENT"

    return "{} | {} | {}".format(
        element_id_text(element),
        category_text(element),
        element_class_text(element)
    )


def find_insert_elements(wall):
    try:
        insert_ids = list(
            wall.FindInserts(True, True, True, True)
        )
        return insert_ids, None
    except Exception as error:
        return [], str(error)


def possible_cutting_elements(wall):
    result = []
    seen_ids = set()

    try:
        dependent_ids = list(wall.GetDependentElements(None))
    except:
        dependent_ids = []

    for element_id in dependent_ids:
        element = doc.GetElement(element_id)
        key = element_id_text(element)

        if key == element_id_text(wall):
            continue

        if element is None or element.Category is None:
            continue

        if isinstance(element, DB.Dimension):
            continue

        if key in seen_ids:
            continue

        seen_ids.add(key)
        result.append(element_descriptor(element))

    try:
        cutter_ids = list(
            DB.InstanceVoidCutUtils.GetCuttingVoidInstances(wall)
        )
    except:
        cutter_ids = []

    for element_id in cutter_ids:
        element = doc.GetElement(element_id)
        key = element_id_text(element)

        if key in seen_ids:
            continue

        seen_ids.add(key)
        result.append(
            "{} | VOID CUTTER".format(
                element_descriptor(element)
            )
        )

    return result


def collect_facade_wall_diagnostic(
    facade,
    wall,
    active_openings,
    document_openings,
    active_opening_ids,
    document_opening_ids
):
    active_hosted = []
    document_hosted = []

    for opening in active_openings:
        host = host_element(opening)

        if host is not None and host.Id.Equals(wall.Id):
            active_hosted.append(opening)

    for opening in document_openings:
        host = host_element(opening)

        if host is not None and host.Id.Equals(wall.Id):
            document_hosted.append(opening)

    insert_ids, find_inserts_error = find_insert_elements(wall)
    insert_descriptors = []

    for insert_id in insert_ids:
        insert_descriptors.append(
            element_descriptor(doc.GetElement(insert_id))
        )

    possible_cutters = []

    if (
        len(active_hosted) == 0
        and len(document_hosted) == 0
        and len(insert_ids) == 0
    ):
        possible_cutters = possible_cutting_elements(wall)

    if len(active_hosted) == 0 and (
        len(document_hosted) > 0
        or len(insert_ids) > 0
    ):
        root_cause = (
            "OPENING DISCOVERY IS TOO VIEW-DEPENDENT"
        )
    elif (
        len(active_hosted) == 0
        and len(document_hosted) == 0
        and len(insert_ids) == 0
    ):
        if len(possible_cutters) > 0:
            root_cause = "NON_DOOR_WINDOW_OR_DEPENDENT_CUTTER_CANDIDATE"
        else:
            root_cause = "NO INSERT ELEMENT REPORTED"
    else:
        root_cause = "NONE"

    try:
        function_text = wall.WallType.Function.ToString()
    except:
        function_text = str(wall.WallType.Function)

    facade_wall_diagnostics.append({
        "facade": facade,
        "wall_id": element_id_text(wall),
        "wall_type": element_name(wall.WallType),
        "function": function_text,
        "active_count": len(active_hosted),
        "document_count": len(document_hosted),
        "find_inserts_count": len(insert_ids),
        "insert_ids": ", ".join([
            insert_id.ToString()
            for insert_id in insert_ids
        ]) or "NONE",
        "insert_descriptors": "; ".join(insert_descriptors) or "NONE",
        "find_inserts_error": find_inserts_error or "NONE",
        "possible_cutters": "; ".join(possible_cutters) or "NONE",
        "root_cause": root_cause
    })

    for opening in document_hosted:
        opening_id = element_id_text(opening)
        family_name, type_name = element_type_data(opening)
        facade_opening_diagnostics.append({
            "facade": facade,
            "wall_id": element_id_text(wall),
            "opening_id": opening_id,
            "family": family_name,
            "type": type_name,
            "host_wall_id": element_id_text(host_element(opening)),
            "in_active": (
                "YES" if opening_id in active_opening_ids else "NO"
            ),
            "in_document": (
                "YES" if opening_id in document_opening_ids else "NO"
            ),
            "level": opening_level_text(opening),
            "wall_base": wall_base_constraint_text(wall),
            "wall_top": wall_top_constraint_text(wall),
            "created_phase": created_phase_text(opening),
            "demolished_phase": demolished_phase_text(opening),
            "left_count": family_reference_count(
                opening,
                DB.FamilyInstanceReferenceType.Left
            ),
            "right_count": family_reference_count(
                opening,
                DB.FamilyInstanceReferenceType.Right
            )
        })


def wall_plan_data(wall):
    try:
        curve = wall.Location.Curve
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
    except:
        return None

    dx = abs(p1.X - p0.X)
    dy = abs(p1.Y - p0.Y)

    if dy < 0.001:
        direction = "HORIZONTAL"
        facade_coordinate = (p0.Y + p1.Y) / 2.0
        span_min = min(p0.X, p1.X)
        span_max = max(p0.X, p1.X)
    elif dx < 0.001:
        direction = "VERTICAL"
        facade_coordinate = (p0.X + p1.X) / 2.0
        span_min = min(p0.Y, p1.Y)
        span_max = max(p0.Y, p1.Y)
    else:
        direction = "OTHER"
        facade_coordinate = 0.0
        span_min = 0.0
        span_max = 0.0

    return {
        "direction": direction,
        "facade_coordinate": facade_coordinate,
        "span_min": span_min,
        "span_max": span_max,
        "p0": p0,
        "p1": p1
    }


def span_overlap_length(first, second):
    return max(
        0.0,
        min(first["span_max"], second["span_max"])
        - max(first["span_min"], second["span_min"])
    )


def wall_exterior_face_data(wall):
    plan_data = wall_plan_data(wall)

    if plan_data is None:
        return None

    try:
        references = DB.HostObjectUtils.GetSideFaces(
            wall,
            DB.ShellLayerType.Exterior
        )
    except:
        return None

    candidates = []

    for reference in references:
        try:
            face = wall.GetGeometryObjectFromReference(reference)
        except:
            continue

        if not isinstance(face, DB.PlanarFace):
            continue

        normal = face.FaceNormal.Normalize()

        try:
            outward = wall.Orientation.Normalize()
        except:
            outward = normal

        if plan_data["direction"] == "HORIZONTAL":
            if abs(normal.Y) < 0.90:
                continue

            coordinate = face.Origin.Y
            normal_component = outward.Y
        elif plan_data["direction"] == "VERTICAL":
            if abs(normal.X) < 0.90:
                continue

            coordinate = face.Origin.X
            normal_component = outward.X
        else:
            continue

        try:
            area = face.Area
        except:
            area = 0.0

        candidates.append({
            "reference": reference,
            "face": face,
            "coordinate": coordinate,
            "normal_component": normal_component,
            "area": area,
            "plan": plan_data
        })

    if len(candidates) == 0:
        return None

    candidates.sort(
        key=lambda item: -item["area"]
    )
    return candidates[0]


def facade_desired_normal(facade):
    return {
        "TOP": 1.0,
        "BOTTOM": -1.0,
        "LEFT": -1.0,
        "RIGHT": 1.0
    }[facade]


def facade_expected_direction(facade):
    if facade in ["TOP", "BOTTOM"]:
        return "HORIZONTAL"

    return "VERTICAL"


def facade_plane_tolerance(seed_wall, candidate_wall):
    try:
        seed_width = seed_wall.Width
    except:
        seed_width = 0.0

    try:
        candidate_width = candidate_wall.Width
    except:
        candidate_width = 0.0

    # Location-line choices and compound widths may differ between segments.
    # The actual exterior faces are compared first; this dynamic allowance is
    # only the façade-band tolerance, not an opening/reference fallback.
    return max(
        0.05,
        seed_width / 2.0 + candidate_width / 2.0 + 0.10
    )


def build_facade_group(facade, seed_wall, exterior_walls):
    seed_face = wall_exterior_face_data(seed_wall)
    expected_direction = facade_expected_direction(facade)
    desired_normal = facade_desired_normal(facade)
    members = []
    rejected = []

    for wall in exterior_walls:
        plan_data = wall_plan_data(wall)

        if (
            plan_data is None
            or plan_data["direction"] != expected_direction
        ):
            continue

        face_data = wall_exterior_face_data(wall)

        if face_data is None:
            rejected.append((
                element_id_text(wall),
                "EXTERIOR_FACE_UNAVAILABLE"
            ))
            continue

        normal_matches = (
            face_data["normal_component"] * desired_normal > 0.90
        )

        if not normal_matches and not wall.Id.Equals(seed_wall.Id):
            rejected.append((
                element_id_text(wall),
                "OUTWARD_NORMAL_MISMATCH"
            ))
            continue

        if seed_face is None:
            coordinate_delta = 0.0
        else:
            coordinate_delta = abs(
                face_data["coordinate"]
                - seed_face["coordinate"]
            )

        tolerance = facade_plane_tolerance(
            seed_wall,
            wall
        )

        if (
            coordinate_delta > tolerance
            and not wall.Id.Equals(seed_wall.Id)
        ):
            rejected.append((
                element_id_text(wall),
                "OUTSIDE_EXTERIOR_FACE_BAND"
            ))
            continue

        members.append({
            "wall": wall,
            "face": face_data,
            "coordinate_delta": coordinate_delta,
            "plane_tolerance": tolerance
        })

    if not any([
        item["wall"].Id.Equals(seed_wall.Id)
        for item in members
    ]):
        members.append({
            "wall": seed_wall,
            "face": seed_face,
            "coordinate_delta": 0.0,
            "plane_tolerance": facade_plane_tolerance(
                seed_wall,
                seed_wall
            )
        })

    members.sort(
        key=lambda item: item["face"]["plan"]["span_min"]
        if item["face"] is not None
        else 0.0
    )

    return {
        "facade": facade,
        "seed_wall": seed_wall,
        "members": members,
        "walls": [item["wall"] for item in members],
        "rejected": rejected
    }


def collect_host_mismatch_detail(opening, host, facade_walls):
    host_data = wall_plan_data(host)
    family_name, type_name = element_type_data(opening)
    candidates = []

    if host_data is not None:
        for facade, facade_wall in facade_walls:
            if facade_wall is None:
                continue

            facade_data = wall_plan_data(facade_wall)

            if facade_data is None:
                continue

            if host_data["direction"] != facade_data["direction"]:
                continue

            coordinate_delta = abs(
                host_data["facade_coordinate"]
                - facade_data["facade_coordinate"]
            )
            overlap_length = span_overlap_length(
                host_data,
                facade_data
            )
            candidates.append((
                coordinate_delta,
                -overlap_length,
                facade,
                facade_wall,
                facade_data,
                overlap_length
            ))

    candidates.sort(key=lambda item: (item[0], item[1]))

    if len(candidates) > 0:
        selected = candidates[0]
        nearest_facade = selected[2]
        selected_wall = selected[3]
        coordinate_delta = selected[0]
        overlap_length = selected[5]
        same_direction = "YES"
        collinear = "YES" if coordinate_delta < 0.001 else "NO"
    else:
        nearest_facade = "NONE"
        selected_wall = None
        coordinate_delta = None
        overlap_length = 0.0
        same_direction = "NO"
        collinear = "NO"

    try:
        function_text = host.WallType.Function.ToString()
    except:
        function_text = str(host.WallType.Function)

    if host_data is None:
        host_direction = "UNSUPPORTED"
        host_coordinate = "-"
        host_endpoints = "-"
    else:
        host_direction = host_data["direction"]
        host_coordinate = "{:.6f}".format(
            host_data["facade_coordinate"]
        )
        host_endpoints = (
            "({:.3f}, {:.3f}) -> ({:.3f}, {:.3f})".format(
                host_data["p0"].X,
                host_data["p0"].Y,
                host_data["p1"].X,
                host_data["p1"].Y
            )
        )

    host_mismatch_details.append({
        "opening_id": element_id_text(opening),
        "family": family_name,
        "type": type_name,
        "host_wall_id": element_id_text(host),
        "host_wall_type": element_name(host.WallType),
        "host_function": function_text,
        "host_direction": host_direction,
        "host_coordinate": host_coordinate,
        "host_endpoints": host_endpoints,
        "nearest_facade": nearest_facade,
        "selected_wall_id": element_id_text(selected_wall),
        "same_direction": same_direction,
        "coordinate_delta": (
            "{:.6f}".format(coordinate_delta)
            if coordinate_delta is not None
            else "-"
        ),
        "span_overlap": "{:.6f}".format(overlap_length),
        "collinear": collinear,
        "host_in_active_view": (
            "YES" if element_id_text(host) in active_wall_ids else "NO"
        ),
        "host_is_selected_boundary": (
            "YES" if element_id_text(host) in boundary_wall_ids else "NO"
        )
    })


def classify_outside_active_view(element, host_visible, bbox_exists):
    if phase_mismatch_confirmed(element):
        return "PHASE_MISMATCH"

    if design_option_mismatch_confirmed(element):
        return "DESIGN_OPTION_MISMATCH"

    if host_visible:
        return "HOST_VISIBLE_BUT_OPENING_NOT_IN_VIEW_COLLECTOR"

    if not bbox_exists:
        return "VIEW_RANGE_OR_VISIBILITY_CONTEXT"

    return "OTHER_ACTIVE_VIEW_FILTERING"


def collect_outside_active_view_detail(
    opening,
    active_wall_ids,
    document_opening_ids,
    active_opening_ids
):
    host = host_element(opening)
    opening_id = element_id_text(opening)
    family_name, type_name = element_type_data(opening)
    host_visible = (
        host is not None
        and element_id_text(host) in active_wall_ids
    )
    bbox_exists = bounding_box_in_active_view(opening)
    terminal_reason = classify_outside_active_view(
        opening,
        host_visible,
        bbox_exists
    )

    outside_active_view_details.append({
        "element_id": opening_id,
        "category": category_text(opening),
        "family": family_name,
        "type": type_name,
        "host_wall_id": element_id_text(host),
        "host_visible": "YES" if host_visible else "NO",
        "created_phase": created_phase_text(opening),
        "demolished_phase": demolished_phase_text(opening),
        "view_phase": view_phase_text(),
        "phase_filter": view_phase_filter_text(),
        "design_option": design_option_text(opening),
        "view_design_option": active_view_design_option_text(),
        "bbox_in_view": "YES" if bbox_exists else "NO",
        "in_document": (
            "YES" if opening_id in document_opening_ids else "NO"
        ),
        "in_active_view": (
            "YES" if opening_id in active_opening_ids else "NO"
        ),
        "terminal_reason": terminal_reason
    })

    return terminal_reason


def design_option_text(element):
    try:
        option = element.DesignOption

        if option is not None:
            return element_name(option)
    except:
        pass

    return "Main Model"


def record_diagnostic(
    severity,
    reason_code,
    operation,
    element=None,
    wall=None,
    opening=None,
    detail=None
):
    subject = element

    if subject is None:
        subject = opening

    if subject is None:
        subject = wall

    family_name, type_name = element_type_data(subject)
    wall_type_name = "-"

    if wall is not None:
        try:
            wall_type_name = element_name(wall.WallType)
        except:
            pass

    key = (
        severity,
        reason_code,
        operation,
        element_id_text(subject),
        element_id_text(wall),
        element_id_text(opening),
        wall_type_name,
        family_name,
        type_name,
        design_option_text(subject)
    )

    if key not in diagnostic_events:
        diagnostic_events[key] = {
            "severity": severity,
            "reason_code": reason_code,
            "operation": operation,
            "element_id": element_id_text(subject),
            "wall_id": element_id_text(wall),
            "opening_id": element_id_text(opening),
            "wall_type": wall_type_name,
            "family": family_name,
            "type": type_name,
            "active_view": "{} ({})".format(
                element_name(view),
                element_id_text(view)
            ),
            "phase": view_phase_text(),
            "design_option": design_option_text(subject),
            "detail": detail or "-",
            "count": 0
        }

    diagnostic_events[key]["count"] += 1


def print_diagnostic_summary():
    global diagnostic_summary_printed

    if not DIAGNOSTIC_ENABLED:
        return

    if diagnostic_summary_printed:
        return

    diagnostic_summary_printed = True
    missing_count = 0
    skip_count = 0
    reason_counts = {}

    for event in diagnostic_events.values():
        count = event["count"]

        if event["severity"] == "MISSING":
            missing_count += count
        elif event["severity"] == "SKIP":
            skip_count += count

        reason = event["reason_code"]
        reason_counts[reason] = reason_counts.get(reason, 0) + count

    output.print_md("### Exterior Dimension Diagnostic")
    output.print_md(
        "**Başarılı: {} | Eksik: {} | Skip: {}**".format(
            diagnostic_success_count,
            missing_count,
            skip_count
        )
    )

    if len(reason_counts) == 0:
        output.print_md("Reason code: yok")
    else:
        output.print_md("**Reason-code dağılımı**")

        for reason in sorted(reason_counts):
            output.print_md(
                "- `{}`: {}".format(
                    reason,
                    reason_counts[reason]
                )
            )

    if len(outside_active_view_details) > 0:
        terminal_counts = {}

        for detail in outside_active_view_details:
            reason = detail["terminal_reason"]
            terminal_counts[reason] = terminal_counts.get(reason, 0) + 1

        output.print_md(
            "### OPENING_OUTSIDE_ACTIVE_VIEW ayrıntıları"
        )
        output.print_md("**Terminal neden dağılımı**")

        for reason in sorted(terminal_counts):
            output.print_md(
                "- `{}`: {}".format(
                    reason,
                    terminal_counts[reason]
                )
            )

        rows = []

        for detail in outside_active_view_details:
            rows.append([
                detail["element_id"],
                detail["category"],
                detail["family"],
                detail["type"],
                detail["host_wall_id"],
                detail["host_visible"],
                detail["created_phase"],
                detail["demolished_phase"],
                detail["view_phase"],
                detail["phase_filter"],
                detail["design_option"],
                detail["view_design_option"],
                detail["bbox_in_view"],
                detail["in_document"],
                detail["in_active_view"],
                detail["terminal_reason"]
            ])

        output.print_table(
            table_data=rows,
            columns=[
                "Element ID",
                "Category",
                "Family",
                "Type",
                "Host Wall ID",
                "Host visible",
                "Created Phase",
                "Demolished Phase",
                "View Phase",
                "Phase Filter",
                "Design Option",
                "View Design Option",
                "BBox in view",
                "Document collector",
                "Active-view collector",
                "Terminal Reason"
            ],
            title="Openings outside active-view collector"
        )

        related_ids = sorted(
            outside_active_view_opening_ids.intersection(
                host_mismatch_opening_ids
            )
        )
        output.print_md(
            "**OPENING_HOST_MISMATCH ilişkisi:** "
            "Outside-active-view: {} | Host-mismatch: {} | "
            "Kesişim: {}{}".format(
                len(outside_active_view_opening_ids),
                len(host_mismatch_opening_ids),
                len(related_ids),
                (
                    " | Element IDs: {}".format(", ".join(related_ids))
                    if len(related_ids) > 0
                    else ""
                )
            )
        )

    if len(facade_wall_diagnostics) > 0:
        output.print_md("### Selected façade wall discovery comparison")
        wall_rows = []

        for item in facade_wall_diagnostics:
            wall_rows.append([
                item["facade"],
                item["wall_id"],
                item["wall_type"],
                item["function"],
                item["active_count"],
                item["document_count"],
                item["find_inserts_count"],
                item["insert_ids"],
                item["insert_descriptors"],
                item["possible_cutters"],
                item["root_cause"]
            ])

            output.print_md(
                "**{} | Wall {}**  ".format(
                    item["facade"],
                    item["wall_id"]
                )
                + "ACTIVE VIEW HOSTED OPENINGS: {}  ".format(
                    item["active_count"]
                )
                + "DOCUMENT HOSTED OPENINGS: {}  ".format(
                    item["document_count"]
                )
                + "FINDINSERTS: {}".format(
                    item["find_inserts_count"]
                )
            )

            if item["root_cause"] != "NONE":
                output.print_md(
                    "`ROOT CAUSE CANDIDATE: {}`".format(
                        item["root_cause"]
                    )
                )

            if item["find_inserts_error"] != "NONE":
                output.print_md(
                    "`FindInserts error: {}`".format(
                        item["find_inserts_error"]
                    )
                )

        output.print_table(
            table_data=wall_rows,
            columns=[
                "Façade / Direction",
                "Wall ID",
                "Wall Type",
                "Function",
                "Active Hosted",
                "Document Hosted",
                "FindInserts",
                "Insert IDs",
                "Insert Category / Class",
                "Other Cutter Candidates",
                "Root Cause Candidate"
            ],
            title="Selected façade walls"
        )

    try:
        group_rows = []

        for facade in ["TOP", "BOTTOM", "LEFT", "RIGHT"]:
            group = facade_groups[facade]
            group_wall_ids = set([
                element_id_text(member["wall"])
                for member in group["members"]
            ])
            hosted_ids = []

            for opening in bosluklar:
                host = host_element(opening)

                if (
                    host is not None
                    and element_id_text(host) in group_wall_ids
                ):
                    hosted_ids.append(element_id_text(opening))

            member_text = "; ".join([
                "{} (delta {:.6f}, tol {:.6f})".format(
                    element_id_text(member["wall"]),
                    member["coordinate_delta"],
                    member["plane_tolerance"]
                )
                for member in group["members"]
            ])
            group_rows.append([
                facade,
                element_id_text(group["seed_wall"]),
                len(group["members"]),
                member_text,
                len(hosted_ids),
                ", ".join(hosted_ids) or "NONE",
                len(group["rejected"])
            ])

        output.print_md("### FacadeGroup runtime result")
        output.print_table(
            table_data=group_rows,
            columns=[
                "Façade",
                "Seed Wall",
                "Member Count",
                "Member Walls / Face Delta / Tolerance",
                "Active Hosted Openings",
                "Opening IDs",
                "Rejected Candidates"
            ],
            title="Multi-segment façade groups used by opening chains"
        )
    except Exception as error:
        output.print_md(
            "`FacadeGroup diagnostic failed: {}`".format(
                str(error)
            )
        )

    if len(facade_opening_diagnostics) > 0:
        opening_rows = []

        for item in facade_opening_diagnostics:
            opening_rows.append([
                item["facade"],
                item["opening_id"],
                item["family"],
                item["type"],
                item["host_wall_id"],
                item["in_active"],
                item["in_document"],
                item["level"],
                item["wall_base"],
                item["wall_top"],
                item["created_phase"],
                item["demolished_phase"],
                item["left_count"],
                item["right_count"]
            ])

        output.print_table(
            table_data=opening_rows,
            columns=[
                "Façade",
                "Opening ID",
                "Family",
                "Type",
                "Host Wall ID",
                "Active collector",
                "Document collector",
                "Opening Level",
                "Wall Base",
                "Wall Top",
                "Created Phase",
                "Demolished Phase",
                "Left refs",
                "Right refs"
            ],
            title="Direct-hosted Door/Window details"
        )

    if len(host_mismatch_details) > 0:
        output.print_md("### OPENING_HOST_MISMATCH façade mapping")
        mismatch_rows = []
        facade_counts = {}
        collinear_count = 0

        for item in host_mismatch_details:
            facade = item["nearest_facade"]
            facade_counts[facade] = facade_counts.get(facade, 0) + 1

            if item["collinear"] == "YES":
                collinear_count += 1

            mismatch_rows.append([
                item["opening_id"],
                item["family"],
                item["type"],
                item["host_wall_id"],
                item["host_wall_type"],
                item["host_function"],
                item["host_direction"],
                item["host_coordinate"],
                item["host_endpoints"],
                item["nearest_facade"],
                item["selected_wall_id"],
                item["same_direction"],
                item["coordinate_delta"],
                item["span_overlap"],
                item["collinear"],
                item["host_in_active_view"],
                item["host_is_selected_boundary"]
            ])

        output.print_table(
            table_data=mismatch_rows,
            columns=[
                "Opening ID",
                "Family",
                "Type",
                "Host Wall ID",
                "Host Wall Type",
                "Host Function",
                "Host Direction",
                "Host Façade Coord",
                "Host Endpoints",
                "Nearest Façade",
                "Selected Wall ID",
                "Same Direction",
                "Coordinate Delta",
                "Span Overlap",
                "Collinear",
                "Host in Active View",
                "Host is Selected Wall"
            ],
            title="Mismatch opening host walls vs selected façade walls"
        )
        output.print_md(
            "**Mismatch façade dağılımı:** {}".format(
                ", ".join([
                    "{}: {}".format(facade, facade_counts[facade])
                    for facade in sorted(facade_counts)
                ])
            )
        )
        output.print_md(
            "**Seçilen façade wall ile tam collinear host sayısı:** "
            "{} / {}**".format(
                collinear_count,
                len(host_mismatch_details)
            )
        )


def side_reference(wall, label):
    try:
        references = DB.HostObjectUtils.GetSideFaces(
            wall,
            DB.ShellLayerType.Exterior
        )

        if references is None or references.Count == 0:
            raise Exception("Exterior side reference collection is empty")

        return references[0]

    except Exception as error:
        record_diagnostic(
            "MISSING",
            "WALL_SIDE_REFERENCE_MISSING",
            "GET_EXTERIOR_SIDE_REFERENCE_{}".format(label),
            element=wall,
            wall=wall,
            detail=str(error)
        )
        print_diagnostic_summary()
        raise


def create_dimension(line, refs, operation):
    global diagnostic_success_count

    try:
        dimension = doc.Create.NewDimension(view, line, refs)
        diagnostic_success_count += 1
        return dimension
    except Exception as error:
        record_diagnostic(
            "MISSING",
            "DIMENSION_CREATION_FAILED",
            operation,
            detail=str(error)
        )
        print_diagnostic_summary()
        raise


# --------------------------------------------------
# 1. DIS DUVARLARI BUL
# --------------------------------------------------

walls = DB.FilteredElementCollector(doc, view.Id)\
    .OfCategory(DB.BuiltInCategory.OST_Walls)\
    .WhereElementIsNotElementType()\
    .ToElements()

dis_duvarlar = []

for wall in walls:
    wall_type = doc.GetElement(wall.GetTypeId())

    if wall_type.Function == DB.WallFunction.Exterior:
        dis_duvarlar.append(wall)
    else:
        record_diagnostic(
            "SKIP",
            "WALL_FUNCTION_NOT_EXTERIOR",
            "FILTER_EXTERIOR_WALLS",
            element=wall,
            wall=wall
        )


# --------------------------------------------------
# 2. UST - ALT - SOL - SAG DUVARLARI BUL
# --------------------------------------------------

ust_duvar = None
alt_duvar = None
sol_duvar = None
sag_duvar = None

ust_y = None
alt_y = None
sol_x = None
sag_x = None


for wall in dis_duvarlar:

    curve = wall.Location.Curve

    start = curve.GetEndPoint(0)
    end = curve.GetEndPoint(1)

    dx = abs(end.X - start.X)
    dy = abs(end.Y - start.Y)

    orta_x = (start.X + end.X) / 2.0
    orta_y = (start.Y + end.Y) / 2.0

    # YATAY DUVARLAR
    if dy < 0.001:

        if ust_y is None or orta_y > ust_y:
            ust_y = orta_y
            ust_duvar = wall

        if alt_y is None or orta_y < alt_y:
            alt_y = orta_y
            alt_duvar = wall

    # DIKEY DUVARLAR
    elif dx < 0.001:

        if sol_x is None or orta_x < sol_x:
            sol_x = orta_x
            sol_duvar = wall

        if sag_x is None or orta_x > sag_x:
            sag_x = orta_x
            sag_duvar = wall


# --------------------------------------------------
# 3. DIS YUZ REFERANSLARI
# --------------------------------------------------

for boundary_label, boundary_wall in [
    ("TOP", ust_duvar),
    ("BOTTOM", alt_duvar),
    ("LEFT", sol_duvar),
    ("RIGHT", sag_duvar)
]:
    if boundary_wall is None:
        record_diagnostic(
            "MISSING",
            "EXTERIOR_BOUNDARY_NOT_FOUND",
            "SELECT_{}_BOUNDARY".format(boundary_label),
            detail="No exterior wall matched the required boundary direction"
        )

ust_ref = side_reference(ust_duvar, "TOP")
alt_ref = side_reference(alt_duvar, "BOTTOM")
sol_ref = side_reference(sol_duvar, "LEFT")
sag_ref = side_reference(sag_duvar, "RIGHT")

facade_groups = {
    "TOP": build_facade_group(
        "TOP",
        ust_duvar,
        dis_duvarlar
    ),
    "BOTTOM": build_facade_group(
        "BOTTOM",
        alt_duvar,
        dis_duvarlar
    ),
    "LEFT": build_facade_group(
        "LEFT",
        sol_duvar,
        dis_duvarlar
    ),
    "RIGHT": build_facade_group(
        "RIGHT",
        sag_duvar,
        dis_duvarlar
    )
}


# --------------------------------------------------
# 4. KAPI VE PENCERELERI BUL
# --------------------------------------------------

doors = DB.FilteredElementCollector(doc, view.Id)\
    .OfCategory(DB.BuiltInCategory.OST_Doors)\
    .WhereElementIsNotElementType()\
    .ToElements()

windows = DB.FilteredElementCollector(doc, view.Id)\
    .OfCategory(DB.BuiltInCategory.OST_Windows)\
    .WhereElementIsNotElementType()\
    .ToElements()

bosluklar = list(doors) + list(windows)

all_doors = DB.FilteredElementCollector(doc)\
    .OfCategory(DB.BuiltInCategory.OST_Doors)\
    .WhereElementIsNotElementType()\
    .ToElements()

all_windows = DB.FilteredElementCollector(doc)\
    .OfCategory(DB.BuiltInCategory.OST_Windows)\
    .WhereElementIsNotElementType()\
    .ToElements()

active_opening_ids = set([
    element_id_text(opening)
    for opening in bosluklar
])
document_openings = list(all_doors) + list(all_windows)
document_opening_ids = set([
    element_id_text(opening)
    for opening in document_openings
])
active_wall_ids = set([
    element_id_text(wall)
    for wall in walls
])

for opening in document_openings:
    opening_id = element_id_text(opening)

    if opening_id not in active_opening_ids:
        outside_active_view_opening_ids.add(opening_id)
        terminal_reason = collect_outside_active_view_detail(
            opening,
            active_wall_ids,
            document_opening_ids,
            active_opening_ids
        )
        record_diagnostic(
            "MISSING",
            "OPENING_OUTSIDE_ACTIVE_VIEW",
            "COMPARE_DOCUMENT_AND_ACTIVE_VIEW_OPENINGS",
            element=opening,
            opening=opening,
            detail="Terminal reason: {}".format(terminal_reason)
        )

boundary_wall_ids = set([
    element_id_text(wall)
    for wall in [ust_duvar, alt_duvar, sol_duvar, sag_duvar]
    if wall is not None
])
facade_group_wall_ids = set()

for facade_group in facade_groups.values():
    for group_wall in facade_group["walls"]:
        facade_group_wall_ids.add(
            element_id_text(group_wall)
        )

for facade, boundary_wall in [
    ("TOP / HORIZONTAL", ust_duvar),
    ("BOTTOM / HORIZONTAL", alt_duvar),
    ("LEFT / VERTICAL", sol_duvar),
    ("RIGHT / VERTICAL", sag_duvar)
]:
    if boundary_wall is not None:
        collect_facade_wall_diagnostic(
            facade,
            boundary_wall,
            bosluklar,
            document_openings,
            active_opening_ids,
            document_opening_ids
        )

for opening in bosluklar:
    try:
        host = opening.Host
    except:
        host = None

    if host is None:
        record_diagnostic(
            "MISSING",
            "OPENING_HOST_MISSING",
            "VALIDATE_OPENING_HOST",
            element=opening,
            opening=opening
        )
    elif element_id_text(host) not in facade_group_wall_ids:
        host_mismatch_opening_ids.add(
            element_id_text(opening)
        )
        collect_host_mismatch_detail(
            opening,
            host,
            [
                ("TOP", ust_duvar),
                ("BOTTOM", alt_duvar),
                ("LEFT", sol_duvar),
                ("RIGHT", sag_duvar)
            ]
        )
        record_diagnostic(
            "MISSING",
            "OPENING_HOST_MISMATCH",
            "MATCH_OPENING_TO_FACADE_GROUP",
            element=opening,
            wall=host,
            opening=opening
        )

    try:
        location_supported = isinstance(
            opening.Location,
            DB.LocationPoint
        )
    except:
        location_supported = False

    if not location_supported:
        record_diagnostic(
            "MISSING",
            "OPENING_LOCATION_UNSUPPORTED",
            "READ_OPENING_LOCATION",
            element=opening,
            wall=host,
            opening=opening
        )


# --------------------------------------------------
# 5. BIR DUVARDAKI BOSLUKLARI BUL
# --------------------------------------------------

def duvardaki_bosluklar(walls_or_wall, yon):

    bulunanlar = []

    if isinstance(walls_or_wall, list):
        target_walls = walls_or_wall
    else:
        target_walls = [walls_or_wall]

    target_wall_ids = set([
        element_id_text(target_wall)
        for target_wall in target_walls
    ])
    found_opening_ids = set()

    for eleman in bosluklar:

        if (
            eleman.Host
            and element_id_text(eleman.Host) in target_wall_ids
        ):

            if eleman.Location:

                if yon == "X":
                    koordinat = eleman.Location.Point.X
                else:
                    koordinat = eleman.Location.Point.Y

                opening_id = element_id_text(eleman)

                if opening_id not in found_opening_ids:
                    found_opening_ids.add(opening_id)
                    bulunanlar.append((koordinat, eleman))

    bulunanlar.sort(key=lambda x: x[0])

    return [x[1] for x in bulunanlar]


# --------------------------------------------------
# 6. ZINCIR REFERANSLARINI OLUSTUR
# --------------------------------------------------

def opening_references(element, wall):
    try:
        left_refs = element.GetReferences(
            DB.FamilyInstanceReferenceType.Left
        )
    except Exception as error:
        record_diagnostic(
            "MISSING",
            "LEFT_REFERENCE_MISSING",
            "GET_OPENING_LEFT_REFERENCE",
            element=element,
            wall=wall,
            opening=element,
            detail=str(error)
        )
        print_diagnostic_summary()
        raise

    try:
        right_refs = element.GetReferences(
            DB.FamilyInstanceReferenceType.Right
        )
    except Exception as error:
        record_diagnostic(
            "MISSING",
            "RIGHT_REFERENCE_MISSING",
            "GET_OPENING_RIGHT_REFERENCE",
            element=element,
            wall=wall,
            opening=element,
            detail=str(error)
        )
        print_diagnostic_summary()
        raise

    if len(left_refs) == 0:
        record_diagnostic(
            "MISSING",
            "LEFT_REFERENCE_MISSING",
            "GET_OPENING_LEFT_REFERENCE",
            element=element,
            wall=wall,
            opening=element,
            detail="Reference collection is empty"
        )

    if len(right_refs) == 0:
        record_diagnostic(
            "MISSING",
            "RIGHT_REFERENCE_MISSING",
            "GET_OPENING_RIGHT_REFERENCE",
            element=element,
            wall=wall,
            opening=element,
            detail="Reference collection is empty"
        )

    result = []

    if len(left_refs) > 0:
        result.append(left_refs[0])

    if len(right_refs) > 0:
        result.append(right_refs[0])

    return result


def zincir_refs_olustur(
    bas_ref,
    bit_ref,
    wall,
    yon,
    facade_group=None,
    extra_reference_items=None
):
    refs = DB.ReferenceArray()
    refs.Append(bas_ref)

    if facade_group is None:
        opening_walls = wall
    else:
        opening_walls = facade_group["walls"]

    elemanlar = duvardaki_bosluklar(opening_walls, yon)

    if len(elemanlar) == 0:
        record_diagnostic(
            "MISSING",
            "OPENING_NOT_DISCOVERED",
            "COLLECT_OPENINGS_ON_BOUNDARY_WALL_{}".format(yon),
            element=wall,
            wall=wall
        )

    events = []

    for element in elemanlar:
        try:
            point = element.Location.Point
            coordinate = point.X if yon == "X" else point.Y
        except:
            continue

        events.append((coordinate, "OPENING", element))

    if extra_reference_items is not None:
        for coordinate, reference in extra_reference_items:
            events.append((coordinate, "TURN", reference))

    events.sort(key=lambda item: item[0])

    for coordinate, event_kind, value in events:
        if event_kind == "TURN":
            refs.Append(value)
            continue

        for reference in opening_references(value, wall):
            refs.Append(reference)

    refs.Append(bit_ref)
    return refs, len(elemanlar)


# --------------------------------------------------
# 7. TOPLAM REFERANSLARI
# --------------------------------------------------

def toplam_refs_olustur(ref1, ref2):

    refs = DB.ReferenceArray()

    refs.Append(ref1)
    refs.Append(ref2)

    return refs


def wall_vertical_end_reference(wall, target_y):
    options = DB.Options()
    options.ComputeReferences = True
    candidates = []

    try:
        geometry = wall.get_Geometry(options)
    except:
        geometry = None

    if geometry is None:
        return None

    for geometry_object in geometry:
        if not isinstance(geometry_object, DB.Solid):
            continue

        if geometry_object.Volume <= 0:
            continue

        for face in geometry_object.Faces:
            if not isinstance(face, DB.PlanarFace):
                continue

            if face.Reference is None:
                continue

            normal = face.FaceNormal.Normalize()

            if abs(normal.Y) < 0.90:
                continue

            coordinate = face.Origin.Y
            candidates.append((
                abs(coordinate - target_y),
                coordinate,
                face.Reference
            ))

    if len(candidates) == 0:
        return None

    candidates.sort(key=lambda item: item[0])

    if candidates[0][0] > 0.50:
        return None

    return candidates[0][1], candidates[0][2]


def right_turning_wall_reference(vertical_candidate, target_y):
    vertical_x = vertical_candidate["face"]["coordinate"]
    candidates = []

    for wall in dis_duvarlar:
        face_data = wall_exterior_face_data(wall)

        if face_data is None:
            continue

        plan = face_data["plan"]

        if plan["direction"] != "HORIZONTAL":
            continue

        try:
            width = wall.Width
        except:
            width = 0.0

        contact_tolerance = max(0.25, width)

        if not (
            vertical_x >= plan["span_min"] - contact_tolerance
            and vertical_x <= plan["span_max"] + contact_tolerance
        ):
            continue

        candidates.append((
            abs(face_data["coordinate"] - target_y),
            face_data["coordinate"],
            face_data["reference"]
        ))

    if len(candidates) == 0:
        return None

    candidates.sort(key=lambda item: item[0])

    if candidates[0][0] > 1.0:
        return None

    return candidates[0][1], candidates[0][2]


def right_envelope_turn_events():
    """Yalniz sag envelope X koordinati degistiginde ara referans uretir."""
    candidates = []
    events = []

    for wall in dis_duvarlar:
        face_data = wall_exterior_face_data(wall)

        if face_data is None:
            continue

        plan = face_data["plan"]

        if plan["direction"] != "VERTICAL":
            continue

        if face_data["normal_component"] <= 0.90:
            continue

        candidate = {
            "wall": wall,
            "face": face_data,
            "span_min": plan["span_min"],
            "span_max": plan["span_max"]
        }
        candidates.append(candidate)
        events.extend([
            candidate["span_min"],
            candidate["span_max"]
        ])

    unique_events = []

    for value in sorted(events):
        if (
            len(unique_events) == 0
            or abs(value - unique_events[-1]) > 0.01
        ):
            unique_events.append(value)

    intervals = []

    for index in range(len(unique_events) - 1):
        start = unique_events[index]
        end = unique_events[index + 1]

        if end - start <= 0.01:
            continue

        scan_y = (start + end) / 2.0
        crossing = [
            candidate
            for candidate in candidates
            if (
                scan_y >= candidate["span_min"] - 0.01
                and scan_y <= candidate["span_max"] + 0.01
            )
        ]

        if len(crossing) == 0:
            continue

        crossing.sort(
            key=lambda candidate: candidate["face"]["coordinate"],
            reverse=True
        )
        outer_x = crossing[0]["face"]["coordinate"]
        outer_candidates = [
            candidate
            for candidate in crossing
            if abs(
                candidate["face"]["coordinate"] - outer_x
            ) <= 0.05
        ]
        intervals.append({
            "start": start,
            "end": end,
            "outer_x": outer_x,
            "candidates": outer_candidates
        })

    turns = []

    for index in range(1, len(intervals)):
        lower = intervals[index - 1]
        upper = intervals[index]

        if abs(lower["end"] - upper["start"]) > 0.01:
            continue

        # Kolon, join veya modelleme nedeniyle iki Wall'a bolunmus fakat
        # ayni exterior duzlemde devam eden segmentler ara olcu olusturmaz.
        if abs(lower["outer_x"] - upper["outer_x"]) <= 0.05:
            continue

        target_y = (lower["end"] + upper["start"]) / 2.0
        reference_item = None

        for candidate in (
            lower["candidates"] + upper["candidates"]
        ):
            reference_item = wall_vertical_end_reference(
                candidate["wall"],
                target_y
            )

            if reference_item is not None:
                break

        if reference_item is None:
            turning_candidate = lower["candidates"][0]
            reference_item = right_turning_wall_reference(
                turning_candidate,
                target_y
            )

        if reference_item is not None:
            turns.append(reference_item)

    return turns


def right_envelope_overall_refs(alt_boundary_ref, ust_boundary_ref):
    items = [
        (min_y, alt_boundary_ref),
        (max_y, ust_boundary_ref)
    ]

    for reference_item in right_envelope_turn_events():
        coordinate = reference_item[0]

        if coordinate <= min_y + 0.05 or coordinate >= max_y - 0.05:
            continue

        items.append(reference_item)

    items.sort(key=lambda item: item[0])
    cleaned = []

    for coordinate, reference in items:
        duplicate = False

        for old_coordinate, old_reference in cleaned:
            if abs(coordinate - old_coordinate) < 0.01:
                duplicate = True
                break

        if not duplicate:
            cleaned.append((coordinate, reference))

    refs = DB.ReferenceArray()

    for coordinate, reference in cleaned:
        refs.Append(reference)

    return refs


def wall_axis_end_reference(wall, axis, target_coordinate):
    options = DB.Options()
    options.ComputeReferences = True
    candidates = []

    try:
        geometry = wall.get_Geometry(options)
    except:
        geometry = None

    if geometry is None:
        return None

    for geometry_object in geometry:
        if not isinstance(geometry_object, DB.Solid):
            continue

        if geometry_object.Volume <= 0:
            continue

        for face in geometry_object.Faces:
            if not isinstance(face, DB.PlanarFace):
                continue

            if face.Reference is None:
                continue

            normal = face.FaceNormal.Normalize()

            if axis == "X":
                if abs(normal.X) < 0.90:
                    continue

                coordinate = face.Origin.X
            else:
                if abs(normal.Y) < 0.90:
                    continue

                coordinate = face.Origin.Y

            candidates.append((
                abs(coordinate - target_coordinate),
                coordinate,
                face.Reference
            ))

    if len(candidates) == 0:
        return None

    candidates.sort(key=lambda item: item[0])

    if candidates[0][0] > 0.50:
        return None

    return candidates[0][1], candidates[0][2]


def facade_turning_wall_reference(
    facade,
    parallel_candidate,
    target_coordinate
):
    if facade in ["TOP", "BOTTOM"]:
        required_direction = "VERTICAL"
    else:
        required_direction = "HORIZONTAL"

    facade_coordinate = parallel_candidate["face"]["coordinate"]
    candidates = []

    for wall in dis_duvarlar:
        face_data = wall_exterior_face_data(wall)

        if face_data is None:
            continue

        plan = face_data["plan"]

        if plan["direction"] != required_direction:
            continue

        try:
            width = wall.Width
        except:
            width = 0.0

        contact_tolerance = max(0.25, width)

        if not (
            facade_coordinate >= plan["span_min"] - contact_tolerance
            and facade_coordinate <= plan["span_max"] + contact_tolerance
        ):
            continue

        candidates.append((
            abs(face_data["coordinate"] - target_coordinate),
            face_data["coordinate"],
            face_data["reference"]
        ))

    if len(candidates) == 0:
        return None

    candidates.sort(key=lambda item: item[0])

    if candidates[0][0] > 1.0:
        return None

    return candidates[0][1], candidates[0][2]


def facade_envelope_turn_events(facade):
    expected_direction = facade_expected_direction(facade)
    desired_normal = facade_desired_normal(facade)
    candidates = []
    events = []

    for wall in dis_duvarlar:
        face_data = wall_exterior_face_data(wall)

        if face_data is None:
            continue

        plan = face_data["plan"]

        if plan["direction"] != expected_direction:
            continue

        if face_data["normal_component"] * desired_normal <= 0.90:
            continue

        candidate = {
            "wall": wall,
            "face": face_data,
            "span_min": plan["span_min"],
            "span_max": plan["span_max"]
        }
        candidates.append(candidate)
        events.extend([
            candidate["span_min"],
            candidate["span_max"]
        ])

    unique_events = []

    for value in sorted(events):
        if (
            len(unique_events) == 0
            or abs(value - unique_events[-1]) > 0.01
        ):
            unique_events.append(value)

    intervals = []

    for index in range(len(unique_events) - 1):
        start = unique_events[index]
        end = unique_events[index + 1]

        if end - start <= 0.01:
            continue

        scan_coordinate = (start + end) / 2.0
        crossing = [
            candidate
            for candidate in candidates
            if (
                scan_coordinate >= candidate["span_min"] - 0.01
                and scan_coordinate <= candidate["span_max"] + 0.01
            )
        ]

        if len(crossing) == 0:
            continue

        face_coordinates = [
            candidate["face"]["coordinate"]
            for candidate in crossing
        ]

        if facade in ["TOP", "RIGHT"]:
            envelope_coordinate = max(face_coordinates)
        else:
            envelope_coordinate = min(face_coordinates)

        envelope_candidates = [
            candidate
            for candidate in crossing
            if abs(
                candidate["face"]["coordinate"]
                - envelope_coordinate
            ) <= 0.05
        ]
        intervals.append({
            "start": start,
            "end": end,
            "envelope_coordinate": envelope_coordinate,
            "candidates": envelope_candidates
        })

    turns = []

    for index in range(1, len(intervals)):
        before = intervals[index - 1]
        after = intervals[index]

        if abs(before["end"] - after["start"]) > 0.01:
            continue

        if abs(
            before["envelope_coordinate"]
            - after["envelope_coordinate"]
        ) <= 0.05:
            continue

        target_coordinate = (
            before["end"] + after["start"]
        ) / 2.0
        reference_item = None
        axis = "X" if facade in ["TOP", "BOTTOM"] else "Y"

        for candidate in (
            before["candidates"] + after["candidates"]
        ):
            reference_item = wall_axis_end_reference(
                candidate["wall"],
                axis,
                target_coordinate
            )

            if reference_item is not None:
                break

        if reference_item is None:
            reference_item = facade_turning_wall_reference(
                facade,
                before["candidates"][0],
                target_coordinate
            )

        if reference_item is not None:
            turns.append(reference_item)

    return turns


def facade_segmented_overall_refs(
    facade,
    start_coordinate,
    start_reference,
    end_coordinate,
    end_reference
):
    items = [
        (start_coordinate, start_reference),
        (end_coordinate, end_reference)
    ]

    for reference_item in facade_envelope_turn_events(facade):
        coordinate = reference_item[0]

        if (
            coordinate <= start_coordinate + 0.05
            or coordinate >= end_coordinate - 0.05
        ):
            continue

        items.append(reference_item)

    items.sort(key=lambda item: item[0])
    cleaned = []

    for coordinate, reference in items:
        if any([
            abs(coordinate - old_coordinate) < 0.01
            for old_coordinate, old_reference in cleaned
        ]):
            continue

        cleaned.append((coordinate, reference))

    refs = DB.ReferenceArray()

    for coordinate, reference in cleaned:
        refs.Append(reference)

    return refs, max(0, len(cleaned) - 2)


def facade_envelope_wall_ids(facade):
    """Her scan araliginda gercek dis kabukta kalan Wall ID'lerini verir."""
    expected_direction = facade_expected_direction(facade)
    desired_normal = facade_desired_normal(facade)
    candidates = []
    events = []

    for wall in dis_duvarlar:
        face_data = wall_exterior_face_data(wall)

        if face_data is None:
            continue

        plan = face_data["plan"]

        if plan["direction"] != expected_direction:
            continue

        if face_data["normal_component"] * desired_normal <= 0.90:
            continue

        candidate = {
            "wall": wall,
            "face": face_data,
            "span_min": plan["span_min"],
            "span_max": plan["span_max"]
        }
        candidates.append(candidate)
        events.extend([
            candidate["span_min"],
            candidate["span_max"]
        ])

    unique_events = []

    for value in sorted(events):
        if (
            len(unique_events) == 0
            or abs(value - unique_events[-1]) > 0.01
        ):
            unique_events.append(value)

    envelope_ids = set()

    for index in range(len(unique_events) - 1):
        start = unique_events[index]
        end = unique_events[index + 1]

        if end - start <= 0.01:
            continue

        scan_coordinate = (start + end) / 2.0
        crossing = [
            candidate
            for candidate in candidates
            if (
                scan_coordinate >= candidate["span_min"] - 0.01
                and scan_coordinate <= candidate["span_max"] + 0.01
            )
        ]

        if len(crossing) == 0:
            continue

        face_coordinates = [
            candidate["face"]["coordinate"]
            for candidate in crossing
        ]

        if facade in ["TOP", "RIGHT"]:
            envelope_coordinate = max(face_coordinates)
        else:
            envelope_coordinate = min(face_coordinates)

        for candidate in crossing:
            if abs(
                candidate["face"]["coordinate"]
                - envelope_coordinate
            ) <= 0.05:
                envelope_ids.add(
                    element_id_text(candidate["wall"])
                )

    return envelope_ids


def extend_facade_groups_to_full_envelope():
    for facade in ["TOP", "BOTTOM", "LEFT", "RIGHT"]:
        group = facade_groups[facade]
        envelope_ids = facade_envelope_wall_ids(facade)
        seed_face_data = wall_exterior_face_data(
            group["seed_wall"]
        )
        existing_ids = set([
            element_id_text(wall)
            for wall in group["walls"]
        ])

        for wall in dis_duvarlar:
            wall_id = element_id_text(wall)

            if wall_id not in envelope_ids or wall_id in existing_ids:
                continue

            face_data = wall_exterior_face_data(wall)

            if face_data is None:
                continue

            if seed_face_data is None:
                coordinate_delta = 0.0
            else:
                coordinate_delta = abs(
                    face_data["coordinate"]
                    - seed_face_data["coordinate"]
                )

            group["members"].append({
                "wall": wall,
                "face": face_data,
                "coordinate_delta": coordinate_delta,
                "plane_tolerance": facade_plane_tolerance(
                    group["seed_wall"],
                    wall
                )
            })
            group["walls"].append(wall)
            existing_ids.add(wall_id)

        group["members"].sort(
            key=lambda member: member["face"]["plan"]["span_min"]
        )
        group["walls"] = [
            member["wall"]
            for member in group["members"]
        ]


extend_facade_groups_to_full_envelope()


# --------------------------------------------------
# 8. SINIRLARI BUL
# --------------------------------------------------

min_x = min(sol_x, sag_x)
max_x = max(sol_x, sag_x)

min_y = min(alt_y, ust_y)
max_y = max(alt_y, ust_y)

z = ust_duvar.Location.Curve.GetEndPoint(0).Z


# --------------------------------------------------
# 9. OFFSETLER
# --------------------------------------------------

zincir_offset = 3.0
toplam_offset = 6.0

dimension_sayisi = 0


# --------------------------------------------------
# 10. DIMENSIONLARI OLUSTUR
# --------------------------------------------------

with revit.Transaction("Exterior Dimension"):

    # ==============================
    # UST CEPHE
    # ==============================

    refs, bosluk_sayisi = zincir_refs_olustur(
        sol_ref,
        sag_ref,
        ust_duvar,
        "X",
        facade_groups["TOP"],
        facade_envelope_turn_events("TOP")
    )

    if bosluk_sayisi > 0:

        line = DB.Line.CreateBound(
            DB.XYZ(min_x, max_y + zincir_offset, z),
            DB.XYZ(max_x, max_y + zincir_offset, z)
        )

        create_dimension(line, refs, "CREATE_TOP_OPENING_CHAIN")

        dimension_sayisi += 1

    toplam_refs, turn_count = facade_segmented_overall_refs(
        "TOP",
        min_x,
        sol_ref,
        max_x,
        sag_ref
    )

    line = DB.Line.CreateBound(
        DB.XYZ(min_x, max_y + toplam_offset, z),
        DB.XYZ(max_x, max_y + toplam_offset, z)
    )

    create_dimension(line, toplam_refs, "CREATE_TOP_OVERALL")

    dimension_sayisi += 1

    if turn_count > 0:
        dis_toplam_refs = toplam_refs_olustur(sol_ref, sag_ref)
        line = DB.Line.CreateBound(
            DB.XYZ(min_x, max_y + toplam_offset + 3.0, z),
            DB.XYZ(max_x, max_y + toplam_offset + 3.0, z)
        )
        create_dimension(
            line,
            dis_toplam_refs,
            "CREATE_TOP_OUTERMOST_OVERALL"
        )
        dimension_sayisi += 1


    # ==============================
    # ALT CEPHE
    # ==============================

    refs, bosluk_sayisi = zincir_refs_olustur(
        sol_ref,
        sag_ref,
        alt_duvar,
        "X",
        facade_groups["BOTTOM"],
        facade_envelope_turn_events("BOTTOM")
    )

    if bosluk_sayisi > 0:

        line = DB.Line.CreateBound(
            DB.XYZ(min_x, min_y - zincir_offset, z),
            DB.XYZ(max_x, min_y - zincir_offset, z)
        )

        create_dimension(line, refs, "CREATE_BOTTOM_OPENING_CHAIN")

        dimension_sayisi += 1

    toplam_refs, turn_count = facade_segmented_overall_refs(
        "BOTTOM",
        min_x,
        sol_ref,
        max_x,
        sag_ref
    )

    line = DB.Line.CreateBound(
        DB.XYZ(min_x, min_y - toplam_offset, z),
        DB.XYZ(max_x, min_y - toplam_offset, z)
    )

    create_dimension(line, toplam_refs, "CREATE_BOTTOM_OVERALL")

    dimension_sayisi += 1

    if turn_count > 0:
        dis_toplam_refs = toplam_refs_olustur(sol_ref, sag_ref)
        line = DB.Line.CreateBound(
            DB.XYZ(min_x, min_y - toplam_offset - 3.0, z),
            DB.XYZ(max_x, min_y - toplam_offset - 3.0, z)
        )
        create_dimension(
            line,
            dis_toplam_refs,
            "CREATE_BOTTOM_OUTERMOST_OVERALL"
        )
        dimension_sayisi += 1


    # ==============================
    # SOL CEPHE
    # ==============================

    refs, bosluk_sayisi = zincir_refs_olustur(
        alt_ref,
        ust_ref,
        sol_duvar,
        "Y",
        facade_groups["LEFT"],
        facade_envelope_turn_events("LEFT")
    )

    if bosluk_sayisi > 0:

        line = DB.Line.CreateBound(
            DB.XYZ(min_x - zincir_offset, min_y, z),
            DB.XYZ(min_x - zincir_offset, max_y, z)
        )

        create_dimension(line, refs, "CREATE_LEFT_OPENING_CHAIN")

        dimension_sayisi += 1

    toplam_refs, turn_count = facade_segmented_overall_refs(
        "LEFT",
        min_y,
        alt_ref,
        max_y,
        ust_ref
    )

    line = DB.Line.CreateBound(
        DB.XYZ(min_x - toplam_offset, min_y, z),
        DB.XYZ(min_x - toplam_offset, max_y, z)
    )

    create_dimension(line, toplam_refs, "CREATE_LEFT_OVERALL")

    dimension_sayisi += 1

    if turn_count > 0:
        dis_toplam_refs = toplam_refs_olustur(alt_ref, ust_ref)
        line = DB.Line.CreateBound(
            DB.XYZ(min_x - toplam_offset - 3.0, min_y, z),
            DB.XYZ(min_x - toplam_offset - 3.0, max_y, z)
        )
        create_dimension(
            line,
            dis_toplam_refs,
            "CREATE_LEFT_OUTERMOST_OVERALL"
        )
        dimension_sayisi += 1


    # ==============================
    # SAG CEPHE
    # ==============================

    refs, bosluk_sayisi = zincir_refs_olustur(
        alt_ref,
        ust_ref,
        sag_duvar,
        "Y",
        facade_groups["RIGHT"],
        facade_envelope_turn_events("RIGHT")
    )

    if bosluk_sayisi > 0:

        line = DB.Line.CreateBound(
            DB.XYZ(max_x + zincir_offset, min_y, z),
            DB.XYZ(max_x + zincir_offset, max_y, z)
        )

        create_dimension(line, refs, "CREATE_RIGHT_OPENING_CHAIN")

        dimension_sayisi += 1

    toplam_refs, turn_count = facade_segmented_overall_refs(
        "RIGHT",
        min_y,
        alt_ref,
        max_y,
        ust_ref
    )

    line = DB.Line.CreateBound(
        DB.XYZ(max_x + toplam_offset, min_y, z),
        DB.XYZ(max_x + toplam_offset, max_y, z)
    )

    create_dimension(line, toplam_refs, "CREATE_RIGHT_OVERALL")

    dimension_sayisi += 1

    if turn_count > 0:
        dis_toplam_refs = toplam_refs_olustur(alt_ref, ust_ref)
        line = DB.Line.CreateBound(
            DB.XYZ(max_x + toplam_offset + 3.0, min_y, z),
            DB.XYZ(max_x + toplam_offset + 3.0, max_y, z)
        )
        create_dimension(
            line,
            dis_toplam_refs,
            "CREATE_RIGHT_OUTERMOST_OVERALL"
        )
        dimension_sayisi += 1


forms.alert(
    "{} dis dimension olusturuldu!".format(
        dimension_sayisi
    )
)

print_diagnostic_summary()
