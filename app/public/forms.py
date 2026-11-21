from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField
from wtforms.validators import InputRequired, Length, Optional


def strip(value):
    return value.strip() if value else value


class PublicRequestForm(FlaskForm):
    locality = StringField("Locality", filters=[strip], validators=[InputRequired(), Length(min=2, max=160)])
    contact = StringField("Contact details (optional)", filters=[strip], validators=[Optional(), Length(max=255)])
    request_text = TextAreaField("What information or assessment are you requesting?", filters=[strip], validators=[InputRequired(), Length(min=10, max=4000)])
    website = StringField("Leave this blank", filters=[strip], validators=[Optional(), Length(max=120)])
