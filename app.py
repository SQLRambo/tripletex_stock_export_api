"""
Tripletex Product Inventory — Web App
Run directly to start the Waitress server.
"""

import logging
from flask import Flask, render_template, request, Response
import requests as http_requests

from tripletex import (
    create_session, delete_session, fetch_report,
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
    consumer_key = request.form.get("consumer_key", "").strip()
    user_key = request.form.get("user_key", "").strip()
    session_token = request.form.get("session_token", "").strip()

    owns_session = False
    try:
        if session_token:
            log.info("Using provided session token")
        elif consumer_key and user_key:
            log.info("Creating session with consumer/employee tokens")
            try:
                session_token = create_session(consumer_key, user_key)
                owns_session = True
                log.info("Session created successfully")
            except http_requests.HTTPError as e:
                log.error("Session creation failed: %s — %s", e, e.response.text if e.response else "")
                return render_template("index.html", error=f"Autentisering feilet: {e}")
        else:
            return render_template(
                "index.html",
                error="Oppgi enten økt-token eller både forbruker-nøkkel og bruker-nøkkel.",
            )

        try:
            headers, rows = fetch_report(session_token)
        except http_requests.HTTPError as e:
            log.error("fetch_report failed: %s | status: %s | body: %s", e, e.response.status_code if e.response else "N/A", e.response.text if e.response else "")
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


if __name__ == "__main__":
    from waitress import serve
    print("Starting server on http://0.0.0.0:8080")
    serve(app, host="0.0.0.0", port=8080)
