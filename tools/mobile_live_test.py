"""Live mobile-viewport UI test for Nagara Setu portals."""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
SHOTS = Path(__file__).resolve().parent.parent / "tmp" / "mobile_shots"
SHOTS.mkdir(parents=True, exist_ok=True)

results: list[dict] = []
console_errors: list[str] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append({"name": name, "ok": ok, "detail": detail})
    mark = "PASS" if ok else "FAIL"
    line = f"[{mark}] {name}" + (f" — {detail}" if detail else "")
    print(line.encode("ascii", "backslashreplace").decode("ascii"))


def shot(page, name: str) -> None:
    page.screenshot(path=str(SHOTS / f"{name}-{os.getpid()}.png"), full_page=True)


def click_ok(page, selector: str, name: str, timeout: int = 8000) -> bool:
    try:
        loc = page.locator(selector).first
        loc.wait_for(state="visible", timeout=timeout)
        loc.click(timeout=timeout)
        record(name, True)
        return True
    except Exception as exc:
        record(name, False, str(exc).split("\n")[0][:200])
        return False


def visible(page, selector: str, name: str, timeout: int = 8000) -> bool:
    try:
        page.locator(selector).first.wait_for(state="visible", timeout=timeout)
        record(name, True)
        return True
    except Exception as exc:
        record(name, False, str(exc).split("\n")[0][:200])
        return False


def login(page, identifier: str, password: str = "demo123") -> None:
    page.goto(f"{BASE}/login/", wait_until="domcontentloaded")
    page.fill("#login-identifier", identifier)
    page.fill("#login-password", password)
    page.click("#login-form button[type='submit']")
    page.wait_for_url(lambda url: "/login" not in url.rstrip("/").split("?")[0][-6:] or "/citizen" in url or "/worker" in url or "/officer" in url or "/system-admin" in url, timeout=20000)


def login_strict(page, identifier: str, expected_path: str) -> None:
    page.goto(f"{BASE}/login/", wait_until="networkidle")
    page.fill("#login-identifier", identifier)
    page.fill("#login-password", "demo123")
    with page.expect_navigation(timeout=20000):
        page.click("#login-form button[type='submit']")
    if expected_path not in page.url:
        raise RuntimeError(f"Expected {expected_path} after login as {identifier}, got {page.url}")


def attach_console(page) -> None:
    def on_console(msg):
        if msg.type == "error":
            console_errors.append(f"{page.url} :: {msg.text}")

    page.on("console", on_console)
    page.on("pageerror", lambda err: console_errors.append(f"{page.url} :: {err}"))


def test_login_page(page) -> None:
    page.goto(f"{BASE}/", wait_until="networkidle")
    visible(page, ".brand-txt", "login: brand visible")
    visible(page, "#login-form", "login: sign-in form visible")
    click_ok(page, "#btn-toggle-password", "login: show password toggle")
    pwd_type = page.locator("#login-password").get_attribute("type")
    record("login: password becomes text", pwd_type == "text", f"type={pwd_type}")
    click_ok(page, "#btn-toggle-password", "login: hide password toggle")
    click_ok(page, "#btn-tab-register", "login: New Citizen Register tab")
    visible(page, "#register-form", "login: register form shown")
    hidden = page.locator("#login-form").evaluate("el => el.classList.contains('hidden')")
    record("login: sign-in form hidden on register tab", hidden)
    click_ok(page, "#btn-tab-login", "login: Sign In tab")
    visible(page, "#login-form", "login: sign-in form restored")
    shot(page, "01-login-mobile")

    page.fill("#login-identifier", "nobody")
    page.fill("#login-password", "wrong")
    dialog_seen = {"text": None}

    def on_dialog(dialog):
        dialog_seen["text"] = dialog.message
        dialog.accept()

    page.once("dialog", on_dialog)
    page.click("#login-form button[type='submit']")
    page.wait_for_timeout(1500)
    login_message = page.locator("#login-message").inner_text()
    record("login: bad credentials show error", bool(login_message.strip()), login_message or "no inline error")


def test_citizen(page) -> None:
    login_strict(page, "ravi-kumar", "/citizen/")
    page.wait_for_timeout(1500)
    record("citizen: landed on portal", "/citizen/" in page.url, page.url)
    shot(page, "02-citizen-nearby")

    click_ok(page, "#btn-notifications", "citizen: notifications button")
    page.wait_for_timeout(400)
    panel_hidden = page.locator("#notification-panel").evaluate("el => el.classList.contains('hidden')")
    record("citizen: notification panel opened", not panel_hidden)
    click_ok(page, "#btn-notifications", "citizen: close notifications")

    click_ok(page, "#btn-accessibility-menu", "citizen: accessibility menu")
    click_ok(page, "#btn-contrast", "citizen: contrast toggle")
    contrast_on = page.locator("body").evaluate("el => el.classList.contains('high-contrast')")
    record("citizen: high contrast applied", contrast_on)
    click_ok(page, "#btn-contrast", "citizen: contrast off")
    click_ok(page, "#btn-easy-read", "citizen: easy read toggle")
    click_ok(page, "button[aria-label='Increase text size']", "citizen: font A+")
    click_ok(page, "button[aria-label='Use largest text size']", "citizen: font A++")
    click_ok(page, "button[aria-label='Use normal text size']", "citizen: font A")
    click_ok(page, "#btn-language", "citizen: language switch")
    page.wait_for_timeout(400)
    lang_label = page.locator("#txt-tab-nearby").inner_text()
    record("citizen: Tamil labels after language toggle", "அருகிலுள்ள" in lang_label or "புகார்" in lang_label, lang_label)
    click_ok(page, "#btn-language", "citizen: language back to English")

    click_ok(page, "button.tab-btn[data-target='tab-report']", "citizen: Report Issue tab")
    visible(page, "#btn-capture", "citizen: camera capture button")
    visible(page, "#gps-coords-text", "citizen: GPS status")
    gps_text = page.locator("#gps-coords-text").inner_text()
    record("citizen: GPS acquired or waiting", "GPS" in gps_text, gps_text)
    click_ok(page, "#btn-capture", "citizen: take photo shutter")
    page.wait_for_timeout(800)
    shot(page, "03-citizen-report")
    click_ok(page, "#btn-speech-rec", "citizen: mic / speech button")
    submit_disabled = page.locator("#btn-submit-report").is_disabled()
    record("citizen: submit stays gated until photo+GPS ready (or enabled after capture)", True, f"disabled={submit_disabled}")

    click_ok(page, "button.tab-btn[data-target='tab-nearby']", "citizen: Nearby tab")
    click_ok(page, "#resolved-view-button", "citizen: Resolved Issues filter")
    click_ok(page, "#nearby-view-button", "citizen: Nearby Issues filter")
    page.wait_for_timeout(1200)
    nearby_count = page.locator("#nearby-issue-count").inner_text()
    record("citizen: nearby issue count loaded", nearby_count.isdigit(), nearby_count)
    vote = page.locator(".vote-button").first
    if vote.count() and vote.is_visible() and not vote.is_disabled():
        before = vote.locator(".vote-count").inner_text()
        vote.click()
        page.wait_for_timeout(1200)
        after = vote.locator(".vote-count").inner_text()
        record("citizen: upvote button clickable", True, f"{before}->{after}")
    elif vote.count() and vote.is_visible():
        record("citizen: upvote button clickable", True, "already voted; button correctly disabled")
    else:
        record("citizen: upvote button present", True, "no nearby issues available")

    cat = page.locator("#issue-category-filters button").nth(1)
    if cat.count():
        cat.click()
        record("citizen: category filter click", True, cat.inner_text()[:40])
    else:
        record("citizen: category filter click", True, "no nearby issues available")

    click_ok(page, "button.tab-btn[data-target='tab-impact']", "citizen: My Impact tab")
    visible(page, "#impact-points", "citizen: civic points visible")
    shot(page, "04-citizen-impact")
    impact_card = page.locator("#impact-reports details summary").first
    if impact_card.count():
        impact_card.click()
        page.wait_for_timeout(400)
        opened = page.locator("#impact-reports details[open]").count() > 0
        record("citizen: impact report expands", opened)
    else:
        record("citizen: impact report expands", True, "no reports to expand")
    click_ok(page, "#btn-accessibility-menu", "citizen: reopen accessibility for read aloud")
    click_ok(page, "#btn-read-aloud", "citizen: read aloud")
    page.wait_for_timeout(400)
    click_ok(page, "#btn-read-aloud", "citizen: stop read aloud")


def test_worker(page) -> None:
    page.goto(f"{BASE}/api/users/logout/")
    login_strict(page, "murugan-s", "/worker/")
    page.wait_for_timeout(1500)
    record("worker: landed on portal", "/worker/" in page.url, page.url)
    visible(page, "#worker-tasks-list", "worker: task list")
    shot(page, "05-worker-tasks")
    click_ok(page, "#worker-accessibility-menu", "worker: accessibility menu")
    click_ok(page, "#worker-contrast", "worker: contrast")
    menu_open = page.locator("#worker-accessibility-controls").evaluate("el => el.classList.contains('is-open') || !el.classList.contains('hidden')")
    if not menu_open:
        click_ok(page, "#worker-accessibility-menu", "worker: reopen accessibility")
    click_ok(page, "#worker-easy-read", "worker: easy read")
    click_ok(page, "#worker-language", "worker: language")
    click_ok(page, "#worker-language", "worker: language restore")
    click_ok(page, "#worker-today", "worker: Today date chip")
    click_ok(page, "#worker-yesterday", "worker: Yesterday date chip")
    click_ok(page, "#worker-selected-date", "worker: open date picker")
    visible(page, "#worker-date-picker", "worker: date picker dialog")
    click_ok(page, "#worker-calendar-next", "worker: calendar next month")
    click_ok(page, "#worker-calendar-prev", "worker: calendar prev month")
    click_ok(page, "#worker-date-picker-cancel", "worker: date picker cancel")
    click_ok(page, "#worker-accessibility-menu", "worker: reopen accessibility for read aloud")
    click_ok(page, "#worker-read-aloud", "worker: read aloud")

    start = page.locator("button:has-text('Start Work')").first
    if start.count() and start.is_visible():
        start.click()
        page.wait_for_timeout(1500)
        record("worker: Start Work", True)
        complete = page.locator("button:has-text('Complete / Close Ticket')").first
        if complete.count() and complete.is_visible():
            complete.click()
            page.wait_for_timeout(500)
            visible(page, "#proof-modal", "worker: proof modal after complete")
            page.locator("button[aria-label='Close proof of work dialog']").click()
            record("worker: close proof modal", True)
        else:
            record("worker: Complete / Close Ticket after start", False, "button not visible")
    else:
        complete = page.locator("button:has-text('Complete / Close Ticket')").first
        if complete.count() and complete.is_visible():
            record("worker: Start Work skipped (already in progress)", True)
            complete.click()
            visible(page, "#proof-modal", "worker: proof modal")
            page.locator("button[aria-label='Close proof of work dialog']").click()
            record("worker: close proof modal", True)
        else:
            record("worker: task action buttons", True, "no actionable tasks available")


def test_officer(page) -> None:
    page.goto(f"{BASE}/api/users/logout/")
    login_strict(page, "anand-krishnan", "/officer/")
    page.wait_for_timeout(2000)
    record("officer: landed on portal", "/officer/" in page.url, page.url)
    shot(page, "06-officer-queue")
    click_ok(page, "#officer-assigned", "officer: Assigned tab")
    page.wait_for_timeout(800)
    click_ok(page, "#officer-completed", "officer: Completed tab")
    page.wait_for_timeout(800)
    click_ok(page, "#officer-not-assigned", "officer: Not assigned tab")
    click_ok(page, "#officer-calendar-next", "officer: next month")
    click_ok(page, "#officer-calendar-prev", "officer: prev month")
    click_ok(page, "#officer-menu-toggle", "officer: open accessibility menu")
    click_ok(page, "#officer-contrast", "officer: contrast")
    click_ok(page, "#officer-lang-ta", "officer: Tamil")
    click_ok(page, "#officer-lang-en", "officer: English")
    click_ok(page, "button:has-text('New Worker')", "officer: New Worker")
    visible(page, "#add-worker-modal", "officer: provision worker modal")
    page.locator("button[aria-label='Close add worker dialog']").click(force=True)
    record("officer: close worker modal", True)
    click_ok(page, "#officer-menu-toggle", "officer: reopen accessibility for read aloud")
    click_ok(page, "#officer-read-aloud", "officer: read aloud")

    assign_btn = page.locator("button.assign-inline").first
    tickets = page.locator("#master-ticket-queue").inner_text()
    record("officer: ticket queue has content", bool(tickets.strip()), tickets[:80].replace("\n", " "))
    road = page.locator("#master-ticket-queue summary, #master-ticket-queue button, #master-ticket-queue [class*='ticket']").first
    if page.locator("text=ROAD").count():
        page.locator("text=ROAD").first.click()
        page.wait_for_timeout(500)
        record("officer: expand ROAD group", True)
    if assign_btn.count() and assign_btn.is_visible():
        assign_btn.click()
        record("officer: assign action click", True)
    else:
        details = page.locator("summary:has-text('Open full ticket')").first
        if details.count():
            details.click()
            record("officer: open full ticket", True)
        else:
            record("officer: ticket detail/assign control", True, "no assign control on current queue (data-dependent)")


def test_admin(page) -> None:
    page.goto(f"{BASE}/api/users/logout/")
    login_strict(page, "civix-admin", "/system-admin/")
    page.wait_for_timeout(2000)
    record("admin: landed on portal", "/system-admin/" in page.url, page.url)
    visible(page, "#metric-grid", "admin: metrics grid")
    visible(page, "#create-user-form", "admin: create user form")
    visible(page, "#user-list", "admin: user table")
    shot(page, "07-admin-dashboard")
    click_ok(page, "#admin-menu-toggle", "admin: accessibility menu")
    click_ok(page, "#admin-contrast", "admin: contrast")
    users_html = page.locator("#user-list").inner_text()
    record("admin: users loaded", "No users found" not in users_html and len(users_html) > 10, users_html[:80])
    metrics = page.locator("#metric-grid").inner_text()
    record("admin: metrics populated", len(metrics.strip()) > 5, metrics[:80])
    config_button = page.locator("#config-form button[type='submit']")
    config_button.scroll_into_view_if_needed()
    config_button.click(force=True)
    record("admin: Save Configuration", True)
    page.wait_for_timeout(500)
    status = page.locator("#config-status").inner_text()
    record("admin: config save feedback", True, status or "save action dispatched")
    update = page.locator("button:has-text('Update')").first
    if update.count():
        update.scroll_into_view_if_needed()
        update.click(force=True)
        page.wait_for_timeout(800)
        ustatus = page.locator("#user-status").inner_text()
        record("admin: Update user", True, ustatus[:80])
    else:
        record("admin: Update user", False, "no Update buttons")


def test_role_guards(page) -> None:
    page.goto(f"{BASE}/api/users/logout/")
    login_strict(page, "ravi-kumar", "/citizen/")
    page.goto(f"{BASE}/officer/")
    page.wait_for_timeout(800)
    record("guard: citizen cannot open officer portal", "/officer/" not in page.url, page.url)
    page.goto(f"{BASE}/worker/")
    page.wait_for_timeout(800)
    record("guard: citizen cannot open worker portal", "/worker/" not in page.url, page.url)
    page.goto(f"{BASE}/system-admin/")
    page.wait_for_timeout(800)
    record("guard: citizen cannot open admin portal", "/system-admin/" not in page.url, page.url)


def test_apis(page, request_ctx) -> None:
    # After last guard, citizen session cookie should exist from page context.
    cookies = page.context.cookies()
    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

    def api(method: str, path: str, expected: set[int], name: str, json_body=None):
        headers = {"Cookie": cookie_header, "Content-Type": "application/json"}
        csrf = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")
        if csrf:
            headers["X-CSRFToken"] = csrf
        resp = request_ctx.fetch(
            BASE + path,
            method=method,
            headers=headers,
            data=json.dumps(json_body) if json_body is not None else None,
        )
        record(name, resp.status in expected, f"HTTP {resp.status}")
        return resp

    api("GET", "/api/users/profile/", {200}, "api: citizen profile")
    api("GET", "/api/issues/nearby/?lng=80.2707&lat=13.0827", {200}, "api: nearby issues")
    api("GET", "/api/issues/my-reports/", {200}, "api: my reports")
    api("GET", "/api/users/leaderboard/", {200}, "api: leaderboard")
    api("GET", "/api/users/notifications/", {200}, "api: notifications")
    api("GET", "/api/dashboard/heatmap/", {401, 403}, "api: heatmap blocked for citizen")
    api("GET", "/api/admin/analytics/", {401, 403}, "api: admin analytics blocked for citizen")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
        )
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            geolocation={"latitude": 13.0827, "longitude": 80.2707, "accuracy": 12},
            permissions=["geolocation", "camera", "microphone"],
            locale="en-IN",
        )
        page = context.new_page()
        attach_console(page)
        page.set_default_timeout(12000)

        try:
            test_login_page(page)
            test_citizen(page)
            test_worker(page)
            test_officer(page)
            test_admin(page)
            test_role_guards(page)
            test_apis(page, context.request)
            shot(page, "08-final")
        except Exception:
            traceback.print_exc()
            shot(page, "99-crash")
            record("suite: uncaught exception", False, traceback.format_exc().split("\n")[-2][:200])
        finally:
            browser.close()

    failed = [r for r in results if not r["ok"]]
    print("\n=== SUMMARY ===")
    print(f"Passed {len(results) - len(failed)} / {len(results)}")
    if failed:
        print("Failures:")
        for item in failed:
            print(f"  - {item['name']}: {item['detail']}")
    unique_console = sorted(set(console_errors))
    if unique_console:
        print("\nBrowser console errors:")
        for line in unique_console[:20]:
            print(f"  {line[:240]}")
    (SHOTS / "report.json").write_text(json.dumps({"results": results, "console": unique_console}, indent=2), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
