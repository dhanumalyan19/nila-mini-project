"""Local WGS84 polygons provide context, never a building measurement."""
import math

from shapely.geometry import Point, shape
from shapely.errors import GEOSException
from sqlalchemy import select

from .extensions import db
from .models import BuildingSurveyContext, SurveyArea


def validate_geometry(geometry):
    if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError("geometry must be a Polygon or MultiPolygon.")
    if "crs" in geometry:
        raise ValueError("Use WGS84 longitude/latitude; custom CRS is not supported.")
    polygons = [geometry.get("coordinates")] if geometry["type"] == "Polygon" else geometry.get("coordinates")
    if not isinstance(polygons, list) or not polygons:
        raise ValueError("geometry needs nonempty polygon coordinates.")
    count = 0
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError("Each polygon needs an exterior ring.")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Every ring needs at least four positions and must close exactly.")
            for point in ring:
                count += 1
                if count > 2000:
                    raise ValueError("Limit each feature to 2,000 positions.")
                if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or isinstance(v, float) and not math.isfinite(v) for v in point):
                    raise ValueError("Positions must contain two finite numbers: [longitude, latitude].")
                if not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90:
                    raise ValueError("Longitude must be -180 to 180; latitude -90 to 90.")
            if any(abs(a[0] - b[0]) > 180 for a, b in zip(ring, ring[1:])):
                raise ValueError("Antimeridian-crossing areas are not supported; split the area first.")
    try:
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid or polygon.area == 0:
            raise ValueError("Polygon is invalid, self-intersecting, empty, or has zero area. Correct it in your GIS tool.")
    except GEOSException as error:
        raise ValueError("Polygon could not be read. Correct it in your GIS tool.") from error
    return polygon


def associate_building(building, areas=None):
    """Include boundaries, exclude hole interiors, retain all overlapping contexts.

    Call inside the building/import transaction, after stale links are removed
    on a coordinate edit. Existing links are not overwritten.
    """
    if building.latitude is None or building.longitude is None:
        return 0
    if areas is None:
        areas = db.session.scalars(select(SurveyArea).where(SurveyArea.is_synthetic == building.is_synthetic))
    existing = set(db.session.scalars(select(BuildingSurveyContext.survey_area_id).where(BuildingSurveyContext.building_id == building.id)))
    point = Point(float(building.longitude), float(building.latitude))
    added = 0
    for area in areas:
        if area.id in existing or area.is_synthetic != building.is_synthetic:
            continue
        try:
            polygon = validate_geometry(area.geometry)
        except ValueError:
            # Legacy malformed geometry cannot confer geographic context.
            continue
        if polygon.covers(point):
            db.session.add(BuildingSurveyContext(building_id=building.id, survey_area_id=area.id,
                association_method="point_in_polygon", source=area.source,
                notes="WGS84 polygon coverage, including boundary. Regional context only; not a building measurement.",
                is_synthetic=building.is_synthetic))
            existing.add(area.id)
            added += 1
    return added
