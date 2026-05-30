# Landing Page + Signup Integration — Design Spec

**Date:** 2026-05-30
**Scope:** Add a working landing page and signup flow to TrendLens for hackathon demo.

---

## Goal

Wire the already-built `landing.html` (on `origin/main`) into the app, build a matching `signup.html` using the Obsidian Momentum design system, and back it with a real `POST /signup` endpoint that persists users to SQLite and seeds their keywords as tracked domains.

---

## User Flow

```
/landing.html
  → (Get Started / CTA button) →
/signup.html
  → (form submit POST /signup) →
/ (index.html — trend dashboard, pre-seeded with user's keywords as tracked domains)
```

---

## Pages

### `landing.html`
- Already built on `origin/main`. Pull as-is via `git pull`.
- Only change: ensure the "Get Started" / primary CTA button(s) link to `/signup.html`.
- Route already added to `main.py` on `origin/main` as `GET /landing.html`.

### `signup.html`
- New file: `app/static/signup.html`.
- Design: Obsidian Momentum design system (`docs/signup_page/DESIGN.md` + `docs/signup_page/screen.png`).
- Font stack: Plus Jakarta Sans (headlines), Inter (body), JetBrains Mono (metadata/labels).
- Color palette: charcoal background `#131314`, green primary `#22C55E`, subtle borders `#2D2D30`.
- Form fields:
  - **Account section:** First name, Last name, Work email, Password
  - **Product section:** Product type (select dropdown), Target users (text), Business model (pill toggle: B2B / B2C / Both / B2B2C), Product goal (textarea)
  - **Trend Interests section:** Keywords tag input (Enter to add, ✕ to remove)
- Submit button: pill-shaped, green `#22C55E`, black text — "Create account & start tracking →"
- Footer link: "Already have an account? Sign in" (non-functional for demo)
- Form action: `POST /signup`, `application/x-www-form-urlencoded`
- On success: server issues `303 redirect` to `/`

---

## Backend

### Database — `app/db/history.py`

Add a `users` table (created in `init_db()`):

```sql
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    product_type  TEXT DEFAULT '',
    target_users  TEXT DEFAULT '',
    business_model TEXT DEFAULT '',
    product_goal  TEXT DEFAULT '',
    keywords    TEXT DEFAULT '',   -- JSON array stored as string
    created_at  TEXT NOT NULL
)
```

Two new functions:
- `create_user(data: dict) -> None` — inserts a row, raises `ValueError` if email already exists
- `get_user_by_email(email: str) -> dict | None` — returns user row or None

### Password hashing
Use `hashlib.sha256(password.encode()).hexdigest()`. No extra dependencies.

### Endpoint — `app/api/routes.py`

```
POST /signup
Content-Type: application/x-www-form-urlencoded
```

Fields: `first_name`, `last_name`, `email`, `password`, `product_type`, `target_users`, `business_model`, `product_goal`, `keywords` (multi-value or comma-separated).

Logic:
1. Hash password.
2. Call `history_db.create_user(data)`.
3. For each keyword, call `td_db.add_domain(keyword.strip())` to seed tracked domains.
4. Return `RedirectResponse("/", status_code=303)`.
5. On duplicate email: return `400` with a plain error message (demo-grade, no fancy error page).

### Route — `main.py`

Add:
```python
@app.get("/signup.html", include_in_schema=False)
async def signup_page() -> FileResponse:
    return FileResponse("app/static/signup.html", headers={"Cache-Control": "no-cache"})
```

---

## What Is NOT in Scope

- Session cookies / authentication middleware
- Login page (non-functional "Sign in" link is fine for demo)
- Email verification
- Password confirmation field (single password field is sufficient for demo)
- Error pages (plain HTTP error response is acceptable)

---

## Files Changed

| File | Change |
|------|--------|
| `git pull` | Brings in `landing.html`, updated `main.py`, docs |
| `app/static/landing.html` | Update CTA button href to `/signup.html` |
| `app/static/signup.html` | New — full signup page |
| `app/db/history.py` | Add `users` table + `create_user()` + `get_user_by_email()` |
| `app/api/routes.py` | Add `POST /signup` endpoint |
| `main.py` | Add `GET /signup.html` route |
