"""A private OrangeHRM in Docker for the candidates task, so no shared demo can change the data under a run.

Usage: uv run orangehrm_local.py [--down]
Starts the containers (docker-compose.yml), runs OrangeHRM's installer once (examples/orangehrm_install.yaml), and
adds the vacancies that examples/orangehrm-candidates.csv uses. Then teach on http://localhost:8200 with teach_live.py.
"""
import argparse
import csv
import subprocess
import time

import httpx
from playwright.sync_api import sync_playwright

import config
import teach

URL = "http://localhost:8200"
API = f"{URL}/web/index.php/api/v2"
LOGIN_URL = f"{URL}/web/index.php/auth/login"
ADMIN_USER, ADMIN_PASSWORD = "Admin", "Teach@Once1"  # examples/orangehrm_install.yaml
CSV = config.ROOT / "examples" / "orangehrm-candidates.csv"


def compose(*args):
    subprocess.run(["docker", "compose", *args], cwd=config.ROOT, check=True)


def wait_until_up() -> str:
    """Where the site redirects to once the web server answers (the installer until it has run)."""
    for _ in range(120):
        try:
            return httpx.get(URL).headers.get("location", "")
        except httpx.TransportError:
            time.sleep(1)
    raise SystemExit(f"OrangeHRM did not start on {URL}")


def add_vacancies(names: set[str]):
    """Each vacancy needs a job title and a hiring manager (the admin's employee record)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=config.CHROMIUM_PATH)
        page = browser.new_page()
        page.goto(LOGIN_URL)
        page.get_by_placeholder("Username").fill(ADMIN_USER)
        page.get_by_placeholder("Password").fill(ADMIN_PASSWORD)
        page.get_by_role("button", name="Login").click()
        page.wait_for_url("**/dashboard/**")
        api = page.request
        manager = api.get(f"{API}/pim/employees?limit=1").json()["data"][0]["empNumber"]
        titles = {t["title"]: t["id"] for t in api.get(f"{API}/admin/job-titles?limit=0").json()["data"]}
        existing = {v["name"] for v in api.get(f"{API}/recruitment/vacancies?limit=0").json()["data"]}
        for name in sorted(names - existing):
            if name not in titles:
                titles[name] = api.post(f"{API}/admin/job-titles", data={"title": name}).json()["data"]["id"]
            resp = api.post(f"{API}/recruitment/vacancies", data={
                "name": name, "jobTitleId": titles[name], "employeeId": manager, "numOfPositions": None,
                "description": "", "status": True, "isPublished": True})
            if not resp.ok:
                raise SystemExit(f"adding vacancy {name!r} failed: {resp.status} {resp.text()[:200]}")
            print(f"added vacancy {name}")
        browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--down", action="store_true", help="stop the containers (data is kept in Docker volumes)")
    args = ap.parse_args()
    if args.down:
        compose("down")
        raise SystemExit
    compose("up", "-d", "--wait")
    if "installer" in wait_until_up():
        print("Installing OrangeHRM (once, ~20 s)…")
        compose("exec", "-T", "orangehrm", "php", "installer/cli_install.php")
    with CSV.open(newline="") as f:
        add_vacancies({row["vacancy"] for row in csv.DictReader(f)})
    print(f"OrangeHRM is ready: {LOGIN_URL} (login {ADMIN_USER} / {ADMIN_PASSWORD}). "
          f"Put {teach.password_env(LOGIN_URL)}={ADMIN_PASSWORD} in .env.")
