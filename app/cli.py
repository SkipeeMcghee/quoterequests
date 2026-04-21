from __future__ import annotations

import click
from flask import Flask

from app.extensions import db
from app.models import User


def register_cli(app: Flask) -> None:
    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.password_option("--password", prompt=True, confirmation_prompt=True)
    def create_admin(email: str, password: str) -> None:
        normalized_email = _create_admin_user(email, password)
        click.echo(f"Admin user created for {normalized_email}.")

    @app.cli.command("create-dev-admin")
    @click.option("--email", default="admin@local.test", show_default=True)
    @click.option("--password", default="TempPass123!", show_default=True)
    def create_dev_admin(email: str, password: str) -> None:
        normalized_email = _create_admin_user(email, password)
        click.echo("Development admin user created.")
        click.echo(f"Email: {normalized_email}")
        click.echo(f"Password: {password}")


def _create_admin_user(email: str, password: str) -> str:
    normalized_email = email.strip().lower()
    existing_user = User.query.filter_by(email=normalized_email).first()
    if existing_user is not None:
        raise click.ClickException("A user with that email already exists.")

    user = User(email=normalized_email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return normalized_email