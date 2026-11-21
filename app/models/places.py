from ..extensions import db
from .common import Record, Synthetic, choice


class Ward(Record, Synthetic, db.Model):
    __tablename__ = "wards"
    code = db.Column(db.String(40), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    locality = db.Column(db.String(160), nullable=False, index=True)
    public_notes = db.Column(db.Text)


class SurveyArea(Record, Synthetic, db.Model):
    __tablename__ = "survey_areas"
    code = db.Column(db.String(60), nullable=False, unique=True)
    name = db.Column(db.String(160), nullable=False)
    geometry = db.Column(db.JSON, nullable=False)
    geological_context = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(255), nullable=False)
    observed_on = db.Column(db.Date, nullable=False)
    review_status = db.Column(db.String(24), nullable=False, default="unreviewed")


class SurveyLocation(Record, Synthetic, db.Model):
    __tablename__ = "survey_locations"
    code = db.Column(db.String(60), nullable=False, unique=True)
    area_id = db.Column(db.Integer, db.ForeignKey("survey_areas.id"))
    latitude = db.Column(db.Numeric(9, 6), nullable=False)
    longitude = db.Column(db.Numeric(9, 6), nullable=False)
    notes = db.Column(db.Text)
    __table_args__ = (
        db.CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        db.CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
    )


class Building(Record, Synthetic, db.Model):
    __tablename__ = "buildings"
    version_id = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version_id}
    code = db.Column(db.String(60), nullable=False, unique=True)
    name = db.Column(db.String(160), nullable=False)
    ward_id = db.Column(db.Integer, db.ForeignKey("wards.id"), nullable=False, index=True)
    address = db.Column(db.String(255))
    latitude = db.Column(db.Numeric(9, 6))
    longitude = db.Column(db.Numeric(9, 6))
    building_use = db.Column(db.String(40), nullable=False, default="unknown")
    construction_year = db.Column(db.SmallInteger)
    occupied_floors = db.Column(db.SmallInteger)
    ground_contact_rooms = db.Column(db.SmallInteger)
    ventilation = db.Column(db.String(24), nullable=False, default="unknown")
    approximate_occupancy = db.Column(db.Integer)
    hours_of_use_per_day = db.Column(db.Numeric(4, 2))
    private_notes = db.Column(db.Text)
    ward = db.relationship("Ward")
    __table_args__ = (
        db.CheckConstraint("(latitude IS NULL AND longitude IS NULL) OR (latitude IS NOT NULL AND longitude IS NOT NULL)", name="coordinate_pair"),
        db.CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        db.CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        db.CheckConstraint("construction_year BETWEEN 1000 AND 9999", name="year_range"),
        db.CheckConstraint("occupied_floors >= 0 AND ground_contact_rooms >= 0 AND approximate_occupancy >= 0", name="nonnegative_counts"),
        db.CheckConstraint("hours_of_use_per_day BETWEEN 0 AND 24", name="hours_range"),
        choice("ventilation", ("unknown", "natural", "mechanical", "mixed"), "ventilation_values"),
    )


class BuildingSurveyContext(Record, Synthetic, db.Model):
    """A geographic context link, never a copied building measurement."""
    __tablename__ = "building_survey_contexts"
    building_id = db.Column(db.Integer, db.ForeignKey("buildings.id"), nullable=False)
    survey_area_id = db.Column(db.Integer, db.ForeignKey("survey_areas.id"), nullable=False)
    association_method = db.Column(db.String(32), nullable=False)
    source = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text, nullable=False)
    __table_args__ = (
        db.UniqueConstraint("building_id", "survey_area_id"),
        choice("association_method", ("point_in_polygon", "officer_review", "synthetic_fixture"), "association_method_values"),
    )
