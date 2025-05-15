"""Utility functions for usage in fetching data and rendering pages."""

import logging
import os
import re
from datetime import datetime, timedelta, timezone

import requests
from rich.logging import RichHandler
from ruamel.yaml import YAML

DEBUG = os.getenv("DEBUG") is not None

logging.basicConfig(
    level="DEBUG" if DEBUG else "INFO",
    format="%(message)s",
    datefmt="[%Y-%m-%d %H:%M:%S %Z]",
    handlers=[RichHandler(rich_tracebacks=True)],
)

log = logging.getLogger("neh")


def generate_page(page, jinja_env, output_path, **kwargs):
    """Generates a new file in memory from a Jinja template."""
    with open(
        os.path.join(
            output_path,
            page,
        ),
        "w",
    ) as output_file:
        template = jinja_env.get_template(f"{page}.jinja")
        output_file.write(template.render(**kwargs))


def get_yaml_data(filename):
    """Load YAML data from a file."""
    yaml = YAML(typ="safe")
    with open(filename) as data_file:
        return yaml.load(data_file.read())


#
# Functions for getting data from the GitHub API.
#


def _get_github_api_response(url, token=None):
    """Return data from GitHub JSON API."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(url, headers=headers, timeout=10)

    if resp.ok:
        if DEBUG:
            log.debug(
                f"Cached({resp.from_cache}) Expires({resp.expires.strftime('%Y-%m-%d %H:%M:%S %Z')}) {url}"
            )
        return resp.json()
    else:
        log.error(f"{resp.status_code} {url}")
        return None


def get_github_latest_release(project):
    """Fetch and parse github release data and return the latest main release (not a draft or prerelease)."""
    url = f"https://api.github.com/repos/{project['org']}/{project['repo']}/releases/latest"

    release_data = _get_github_api_response(url)

    if release_data and "tag_name" in release_data:
        return release_data

    log.error(f"No latest release found for {project}!")
    return None


def get_github_upstream_testing_results(project):
    """Fetch and parse upstream testing workflow results."""
    url = f"https://api.github.com/repos/{project['org']}/{project['repo']}/actions/workflows/upstream_testing.yml/runs"
    runs_data = _get_github_api_response(url)

    if runs_data is not None:
        latest_run_jobs = _get_github_api_response(runs_data["workflow_runs"][0]["jobs_url"])

        # Highlight if workflow didn't run for more than 3 days
        latest_run_date = datetime.fromisoformat(runs_data["workflow_runs"][0]["updated_at"])
        if datetime.now(timezone.utc) - latest_run_date > timedelta(days=3):
            runs_data["workflow_runs"][0]["updated_at_color"] = "text-danger"

    return {
        "runs": runs_data["workflow_runs"] if runs_data else None,
        "latest_run_jobs": latest_run_jobs["jobs"] if runs_data else None,
    }


#
# Functions for getting data from the PyPI API.
#
def _get_pypi_api_response(project):
    """Return data from PyPI JSON API."""
    url = f"https://pypi.python.org/pypi/{project}/json"
    headers = {"Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=10)

    if resp.ok:
        if DEBUG:
            log.debug(
                f"Cached({resp.from_cache}) Expires({resp.expires.strftime('%Y-%m-%d %H:%M:%S %Z')}) {url}"
            )
        return resp.json()
    else:
        log.error(f"{resp.status_code} {url}")
        return None


def get_pypi_data(project):
    """Fetch and parse package data from PyPI."""
    pypi_raw_data = _get_pypi_api_response(project["pypi"])
    pypi_data = {
        "latest": {
            "version": pypi_raw_data["info"]["version"],
            "requires_python": pypi_raw_data["info"]["requires_python"],
            "requires_nautobot": "N/A",
            "date": pypi_raw_data["urls"][0]["upload_time"].split("T")[0],
        }
    }

    release_date = datetime.fromisoformat(pypi_raw_data["urls"][0]["upload_time"])
    if datetime.now() - release_date > timedelta(weeks=16):
        pypi_data["latest"]["date_color"] = "danger"
    elif datetime.now() - release_date > timedelta(weeks=8):
        pypi_data["latest"]["date_color"] = "warning"
    else:
        pypi_data["latest"]["date_color"] = "success"

    r = re.compile("nautobot[<> ]")
    for result in filter(r.match, pypi_raw_data["info"]["requires_dist"]):
        pypi_data["latest"]["requires_nautobot"] = result

    return pypi_data


# TODO: Might remove it since having visual history is enough.
def _get_run_streak(runs, target_status, opposite_status):
    streak = {"length": 0, "first_run": None, "last_run": None}
    for run in runs:
        if run["conclusion"] == target_status:
            if streak["last_run"] is None:
                streak["last_run"] = streak["first_run"] = run
                streak["length"] = 1
            else:
                streak["first_run"] = run
                streak["length"] += 1
        if run["conclusion"] == opposite_status and streak["last_run"] is not None:
            break
    return streak
