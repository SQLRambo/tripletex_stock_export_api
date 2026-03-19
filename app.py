"""
Tripletex Product Inventory — Web App
Run directly to start the Waitress server.
"""

import logging
from flask import Flask, render_template, request, Response
import requests as http_requests

CONSUMER_TOKEN = "eyJ0b2tlbklkIjo2MTE2LCJ0b2tlbiI6ImUxOGY3MDhhLTVhYzYtNGY0Zi1hMjE2LWM3MzcxMzEwM2VhMSJ9"

from tripletex import (
    create_session, delete_session, fetch_report, fetch_date_report,
    generate_csv_bytes, csv_filename,
)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/export", methods=["POST"])
def export():
    owns_session = False
    session_token = None
    try:
        try:
            session_token, owns_session = _resolve_session(request.form)
        except http_requests.HTTPError as e:
            return render_template("index.html", error=f"Autentisering feilet: {e}")

        if not session_token:
            return render_template(
                "index.html",
                error="Oppgi enten økt-token eller bruker-nøkkel.",
            )

        try:
            headers, rows = fetch_report(session_token)
        except http_requests.HTTPError as e:
            log.error("fetch_report failed: %s", e)
            return render_template("index.html", error=f"API-feil: {e}")

        csv_bytes = generate_csv_bytes(headers, rows)
        filename = csv_filename()

        return Response(
            csv_bytes,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        log.exception("Unexpected error in /export")
        return render_template("index.html", error=f"Uventet feil: {e}")

    finally:
        if owns_session and session_token:
            delete_session(session_token)


def _resolve_session(form):
    """Returns (session_token, owns_session) or raises an error response."""
    user_key = form.get("user_key", "").strip()
    session_token = form.get("session_token", "").strip()

    if session_token:
        log.info("Using provided session token")
        return session_token, False
    elif user_key:
        log.info("Creating session with hardcoded consumer token + employee token")
        try:
            token = create_session(CONSUMER_TOKEN, user_key)
            log.info("Session created successfully")
            return token, True
        except http_requests.HTTPError as e:
            log.error("Session creation failed: %s", e)
            raise
    else:
        return None, False


@app.route("/export-by-date", methods=["POST"])
def export_by_date():
    report_date = request.form.get("report_date", "").strip()
    if not report_date:
        return render_template("index.html", error="Velg en dato for rapporten.")

    owns_session = False
    session_token = None
    try:
        try:
            session_token, owns_session = _resolve_session(request.form)
        except http_requests.HTTPError as e:
            return render_template("index.html", error=f"Autentisering feilet: {e}")

        if not session_token:
            return render_template(
                "index.html",
                error="Oppgi enten økt-token eller bruker-nøkkel.",
            )

        try:
            headers, rows = fetch_date_report(session_token, report_date)
        except http_requests.HTTPError as e:
            log.error("fetch_date_report failed: %s", e)
            return render_template("index.html", error=f"API-feil: {e}")

        csv_bytes = generate_csv_bytes(headers, rows)
        filename = csv_filename(f"lager_{report_date}")

        return Response(
            csv_bytes,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        log.exception("Unexpected error in /export-by-date")
        return render_template("index.html", error=f"Uventet feil: {e}")

    finally:
        if owns_session and session_token:
            delete_session(session_token)


if __name__ == "__main__":
    from waitress import serve
    print("Starting server on http://0.0.0.0:8080")
    serve(app, host="0.0.0.0", port=8080)
