from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import InputRequired, Length, Regexp


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[InputRequired(), Length(max=80), Regexp(r"^[A-Za-z0-9_.-]+$", message="Use letters, numbers, dots, underscores or hyphens.")], filters=[lambda value: value.strip().lower() if value else value])
    password = PasswordField("Password", validators=[InputRequired(), Length(max=256)])
    submit = SubmitField("Sign in")

