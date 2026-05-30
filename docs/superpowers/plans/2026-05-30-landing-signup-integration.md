# Landing + Signup Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull the existing `landing.html` from `origin/main`, wire CTA buttons to a new `signup.html`, build the signup page using the Obsidian Momentum design system, and back it with a working `POST /signup` endpoint that saves users to SQLite and seeds their keywords as tracked domains.

**Architecture:** Pull brings in `landing.html` + updated `main.py`; we update the landing CTA links, add a `users` table to the existing SQLite DB in `history.py`, add `POST /signup` to `routes.py`, serve `signup.html` from `main.py`, and build the signup page as a standalone HTML file.

**Tech Stack:** FastAPI, SQLite (via `sqlite3`), `hashlib` (stdlib), HTML/CSS/vanilla JS (no framework), existing `td_db.add_domain()` for seeding tracked domains.

---

### Task 1: Pull origin/main

**Files:**
- No file edits — git operation only

- [ ] **Step 1: Pull**

```bash
cd /Users/yeganehkhabbazian/Projects/Product_manager_app/trendlens
git pull origin main
```

Expected: `app/static/landing.html` appears, `main.py` gains a `/landing.html` route, `docs/` gains design docs and screenshots.

- [ ] **Step 2: Verify files landed**

```bash
ls app/static/
# Should show: index.html  landing.html
grep "landing" main.py
# Should show the /landing.html route
```

---

### Task 2: Update landing.html CTA buttons to point to signup

**Files:**
- Modify: `app/static/landing.html`

- [ ] **Step 1: Update nav Sign in link**

Find:
```html
<a href="index.html" class="sign-in">Sign in</a>
```
Replace with:
```html
<a href="/signup.html" class="sign-in">Sign in</a>
```

- [ ] **Step 2: Update nav Get Started button**

Find:
```html
<a href="index.html" class="btn-cta">Get Started</a>
```
Replace with:
```html
<a href="/signup.html" class="btn-cta">Get Started</a>
```

- [ ] **Step 3: Update hero Start Researching button**

Find:
```html
<button class="btn-primary" onclick="location.href='index.html'">Start Researching <span>→</span></button>
```
Replace with:
```html
<button class="btn-primary" onclick="location.href='/signup.html'">Start Researching <span>→</span></button>
```

- [ ] **Step 4: Commit**

```bash
git add app/static/landing.html
git commit -m "fix: point landing page CTAs to signup page"
```

---

### Task 3: Add users table and DB functions to history.py

**Files:**
- Modify: `app/db/history.py`

- [ ] **Step 1: Add users table to `_SCHEMA`**

In `app/db/history.py`, the `_SCHEMA` string currently ends with the `product_profiles` table. Append the `users` table before the closing `"""`:

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    UNIQUE NOT NULL,
    domain      TEXT    NOT NULL,
    config_json TEXT    NOT NULL,
    report_json TEXT    NOT NULL,
    topics_json TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_domain     ON snapshots(domain);
CREATE INDEX IF NOT EXISTS idx_snapshots_created_at ON snapshots(created_at);

CREATE TABLE IF NOT EXISTS feedback (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT    NOT NULL,
    domain         TEXT    NOT NULL,
    item_headline  TEXT    NOT NULL,
    feedback_type  TEXT    NOT NULL,
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_domain ON feedback(domain);

CREATE TABLE IF NOT EXISTS product_profiles (
    domain       TEXT    PRIMARY KEY,
    profile_json TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name     TEXT NOT NULL,
    last_name      TEXT NOT NULL,
    email          TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    product_type   TEXT DEFAULT '',
    target_users   TEXT DEFAULT '',
    business_model TEXT DEFAULT '',
    product_goal   TEXT DEFAULT '',
    keywords       TEXT DEFAULT '',
    created_at     TEXT NOT NULL
);
"""
```

- [ ] **Step 2: Add `create_user()` and `get_user_by_email()` functions**

Add these two functions at the bottom of `app/db/history.py`:

```python
def create_user(data: dict) -> None:
    """Insert a new user. Raises ValueError if email already exists."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO users
                    (first_name, last_name, email, password_hash,
                     product_type, target_users, business_model,
                     product_goal, keywords, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["first_name"],
                    data["last_name"],
                    data["email"],
                    data["password_hash"],
                    data.get("product_type", ""),
                    data.get("target_users", ""),
                    data.get("business_model", ""),
                    data.get("product_goal", ""),
                    data.get("keywords", ""),
                    now,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"Email already registered: {data['email']}") from exc
    log.info(f"User created | email={data['email']!r}")


def get_user_by_email(email: str) -> dict | None:
    """Return user row as dict or None if not found."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    return dict(row) if row else None
```

- [ ] **Step 3: Verify the DB migration works**

```bash
cd /Users/yeganehkhabbazian/Projects/Product_manager_app/trendlens
source .venv/bin/activate
python -c "
from app.db import history as h
h.init_db()
h.create_user({'first_name':'Test','last_name':'User','email':'test@example.com','password_hash':'abc123'})
print(h.get_user_by_email('test@example.com'))
"
```

Expected: prints a dict with all user fields populated.

- [ ] **Step 4: Commit**

```bash
git add app/db/history.py
git commit -m "feat: add users table and create_user/get_user_by_email to history DB"
```

---

### Task 4: Add POST /signup endpoint to routes.py

**Files:**
- Modify: `app/api/routes.py`

- [ ] **Step 1: Add missing imports at the top of routes.py**

The file already imports `asyncio`, `APIRouter`, `BackgroundTasks`, `HTTPException`, `Query`. Add the missing ones:

```python
import hashlib
import json

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Query
from fastapi.responses import PlainTextResponse, RedirectResponse
```

- [ ] **Step 2: Add the endpoint at the bottom of routes.py**

```python
@router.post("/signup", include_in_schema=False)
async def signup(
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    product_type: str = Form(""),
    target_users: str = Form(""),
    business_model: str = Form(""),
    product_goal: str = Form(""),
    keywords: str = Form(""),
) -> RedirectResponse:
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

    user_data = {
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "email": email.strip().lower(),
        "password_hash": password_hash,
        "product_type": product_type,
        "target_users": target_users,
        "business_model": business_model,
        "product_goal": product_goal,
        "keywords": json.dumps(keyword_list),
    }

    try:
        await asyncio.to_thread(history_db.create_user, user_data)
    except ValueError:
        raise HTTPException(status_code=400, detail="Email already registered.")

    for keyword in keyword_list:
        try:
            await asyncio.to_thread(td_db.add_domain, keyword)
        except Exception:
            pass  # domain already tracked — fine

    return RedirectResponse("/", status_code=303)
```

- [ ] **Step 3: Commit**

```bash
git add app/api/routes.py
git commit -m "feat: add POST /signup endpoint with user creation and domain seeding"
```

---

### Task 5: Add GET /signup.html route to main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add route inside `create_app()`**

In `main.py`, after the `/landing.html` route (which arrived via `git pull`), add:

```python
    @app.get("/signup.html", include_in_schema=False)
    async def signup_page() -> FileResponse:
        return FileResponse(
            "app/static/signup.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
```

- [ ] **Step 2: Commit**

```bash
git add main.py
git commit -m "feat: add GET /signup.html route"
```

---

### Task 6: Build signup.html

**Files:**
- Create: `app/static/signup.html`

- [ ] **Step 1: Create the file**

Create `app/static/signup.html` with the full content below. Design follows the Obsidian Momentum system: charcoal `#131314` background, green `#22C55E` primary, `#2D2D30` borders, Plus Jakarta Sans headlines, Inter body, JetBrains Mono section labels. Tag input uses safe DOM manipulation (no innerHTML with user data).

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>TrendLens — Create Account</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@600&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:         #131314;
      --surface:    #1C1C1F;
      --border:     #2D2D30;
      --text:       #e5e2e3;
      --text2:      #94A3B8;
      --green:      #22C55E;
      --green-dim:  rgba(34,197,94,0.12);
      --green-brd:  rgba(34,197,94,0.35);
      --purple:     #818CF8;
      --purple-dim: rgba(129,140,248,0.12);
      --purple-brd: rgba(129,140,248,0.35);
      --r-card:     12px;
      --r-pill:     999px;
    }

    html, body { width: 100%; min-height: 100vh; }

    body {
      font-family: "Inter", sans-serif;
      background: var(--bg);
      color: var(--text);
      -webkit-font-smoothing: antialiased;
    }

    header {
      position: sticky; top: 0; z-index: 10;
      height: 64px;
      background: rgba(19,19,20,0.95);
      backdrop-filter: blur(20px);
      border-bottom: 1px solid var(--border);
      display: flex; align-items: center; padding: 0 32px;
    }
    .logo { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--text); }
    .logo-icon {
      width: 30px; height: 30px; border-radius: 8px;
      background: var(--green);
      display: flex; align-items: center; justify-content: center;
      font-size: 15px;
    }
    .logo-text {
      font-family: "Plus Jakarta Sans", sans-serif;
      font-size: 16px; font-weight: 700; letter-spacing: -0.3px;
    }

    .page {
      display: flex; align-items: flex-start; justify-content: center;
      padding: 48px 24px 80px;
      min-height: calc(100vh - 64px);
    }

    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 40px;
      width: 100%; max-width: 560px;
      display: flex; flex-direction: column; gap: 32px;
    }

    .card-header { display: flex; flex-direction: column; gap: 6px; }
    .card-header h1 {
      font-family: "Plus Jakarta Sans", sans-serif;
      font-size: 24px; font-weight: 700; letter-spacing: -0.5px;
    }
    .card-header p { font-size: 14px; color: var(--text2); line-height: 1.5; }

    .section { display: flex; flex-direction: column; gap: 16px; }
    .section-label {
      font-family: "JetBrains Mono", monospace;
      font-size: 11px; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.1em;
      color: var(--text2);
      padding-bottom: 10px;
      border-bottom: 1px solid var(--border);
    }

    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .field { display: flex; flex-direction: column; gap: 6px; }
    .field label { font-size: 12px; font-weight: 600; color: var(--text2); }
    .field input,
    .field textarea,
    .field select {
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: var(--r-card);
      padding: 11px 14px;
      font-size: 14px; color: var(--text);
      font-family: "Inter", sans-serif;
      outline: none; width: 100%;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    .field input::placeholder,
    .field textarea::placeholder { color: var(--text2); }
    .field input:focus,
    .field textarea:focus,
    .field select:focus {
      border-color: var(--purple);
      box-shadow: 0 0 0 3px rgba(129,140,248,0.12);
    }
    .field textarea { resize: vertical; min-height: 80px; line-height: 1.5; }
    .field select { appearance: none; cursor: pointer; }
    .field select option { background: var(--surface); }

    .pill-group { display: flex; gap: 8px; flex-wrap: wrap; }
    .pill {
      padding: 7px 16px; border-radius: var(--r-pill);
      border: 1px solid var(--border);
      font-size: 12px; font-weight: 600; color: var(--text2);
      cursor: pointer; background: transparent;
      font-family: "Inter", sans-serif;
      transition: all 0.15s;
    }
    .pill.active {
      background: var(--green-dim);
      border-color: var(--green-brd);
      color: var(--green);
    }

    .tags-wrap {
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: var(--r-card);
      padding: 10px 12px;
      display: flex; flex-wrap: wrap; gap: 6px;
      cursor: text; min-height: 48px; align-items: center;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    .tags-wrap:focus-within {
      border-color: var(--purple);
      box-shadow: 0 0 0 3px rgba(129,140,248,0.12);
    }
    .tag {
      background: var(--purple-dim);
      border: 1px solid var(--purple-brd);
      color: var(--purple);
      padding: 3px 10px; border-radius: var(--r-pill);
      font-size: 12px; font-weight: 600;
      display: flex; align-items: center; gap: 5px;
    }
    .tag-remove {
      cursor: pointer; color: var(--text2); font-size: 10px;
      line-height: 1; border: none; background: transparent;
      color: var(--text2); padding: 0;
    }
    .tag-remove:hover { color: var(--text); }
    .tags-wrap input {
      background: transparent; border: none; outline: none;
      font-size: 13px; color: var(--text);
      font-family: "Inter", sans-serif;
      padding: 2px 4px; min-width: 140px; flex: 1;
    }
    .tags-wrap input::placeholder { color: var(--text2); }

    .hint { font-size: 11px; color: var(--text2); margin-top: -8px; }

    .btn-submit {
      width: 100%; padding: 14px;
      border-radius: var(--r-pill);
      background: var(--green);
      color: #000; font-size: 15px; font-weight: 700;
      border: none; cursor: pointer;
      font-family: "Plus Jakarta Sans", sans-serif;
      transition: opacity 0.15s, transform 0.1s;
    }
    .btn-submit:hover { opacity: 0.9; }
    .btn-submit:active { transform: scale(0.99); }

    .footer-note { font-size: 13px; color: var(--text2); text-align: center; }
    .footer-note a { color: var(--green); text-decoration: none; font-weight: 600; }
    .footer-note a:hover { text-decoration: underline; }

    .error-banner {
      background: rgba(239,68,68,0.12);
      border: 1px solid rgba(239,68,68,0.3);
      border-radius: var(--r-card);
      padding: 12px 16px;
      font-size: 13px; color: #f87171;
      display: none;
    }
    .error-banner.visible { display: block; }

    @media (max-width: 600px) {
      .card { padding: 24px 20px; }
      .row { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>

<header>
  <a href="/landing.html" class="logo">
    <div class="logo-icon">🔭</div>
    <div class="logo-text">TrendLens</div>
  </a>
</header>

<div class="page">
  <div class="card">

    <div class="card-header">
      <h1>Create your account</h1>
      <p>Tell us about your product so TrendLens can personalise your trend signals from day one.</p>
    </div>

    <form method="POST" action="/signup" id="signup-form">

      <div class="section">
        <div class="section-label">Account</div>
        <div class="row">
          <div class="field">
            <label for="first_name">First name</label>
            <input type="text" id="first_name" name="first_name" placeholder="Yeganeh" required/>
          </div>
          <div class="field">
            <label for="last_name">Last name</label>
            <input type="text" id="last_name" name="last_name" placeholder="K." required/>
          </div>
        </div>
        <div class="field">
          <label for="email">Work email</label>
          <input type="email" id="email" name="email" placeholder="you@company.com" required/>
        </div>
        <div class="field">
          <label for="password">Password</label>
          <input type="password" id="password" name="password" placeholder="••••••••" required minlength="8"/>
        </div>
      </div>

      <div class="section">
        <div class="section-label">Your Product</div>

        <div class="field">
          <label for="product_type">Type of product</label>
          <select id="product_type" name="product_type">
            <option value="" disabled selected>Select a category…</option>
            <option value="SaaS / Software">SaaS / Software</option>
            <option value="Marketplace">Marketplace</option>
            <option value="Developer Tool">Developer Tool</option>
            <option value="Fintech">Fintech</option>
            <option value="Healthcare">Healthcare</option>
            <option value="E-commerce">E-commerce</option>
            <option value="EdTech">EdTech</option>
            <option value="Hardware">Hardware</option>
            <option value="Other">Other</option>
          </select>
        </div>

        <div class="field">
          <label for="target_users">Who are your users?</label>
          <input type="text" id="target_users" name="target_users"
            placeholder="e.g. enterprise engineers, small business owners"/>
        </div>

        <div class="field">
          <label>Business model</label>
          <div class="pill-group" id="biz-model-group">
            <button type="button" class="pill active" data-value="B2B">B2B</button>
            <button type="button" class="pill" data-value="B2C">B2C</button>
            <button type="button" class="pill" data-value="Both">Both</button>
            <button type="button" class="pill" data-value="B2B2C">B2B2C</button>
          </div>
          <input type="hidden" id="business_model" name="business_model" value="B2B"/>
        </div>

        <div class="field">
          <label for="product_goal">Goal of your product</label>
          <textarea id="product_goal" name="product_goal"
            placeholder="e.g. Help finance teams automate expense reporting and reduce approval time by 50%"></textarea>
        </div>
      </div>

      <div class="section">
        <div class="section-label">Trend Interests</div>
        <div class="field">
          <label>Keywords you care about</label>
          <div class="tags-wrap" id="tags-wrap">
            <input type="text" id="tag-input" placeholder="Type a keyword and press Enter…"/>
          </div>
          <input type="hidden" id="keywords-value" name="keywords"/>
          <div class="hint">These shape which signals TrendLens surfaces for you.</div>
        </div>
      </div>

      <div class="error-banner" id="error-banner"></div>

      <button type="submit" class="btn-submit">Create account &amp; start tracking →</button>

    </form>

    <div class="footer-note">Already have an account? <a href="/">Sign in</a></div>

  </div>
</div>

<script>
  // Pill toggle — business model
  document.getElementById('biz-model-group').addEventListener('click', function(e) {
    var btn = e.target.closest('.pill');
    if (!btn) return;
    document.querySelectorAll('#biz-model-group .pill').forEach(function(p) {
      p.classList.remove('active');
    });
    btn.classList.add('active');
    document.getElementById('business_model').value = btn.getAttribute('data-value');
  });

  // Tag input — uses safe DOM methods, no innerHTML with user data
  var tagsWrap = document.getElementById('tags-wrap');
  var tagInput = document.getElementById('tag-input');
  var keywordsHidden = document.getElementById('keywords-value');
  var tags = [];

  function buildTagEl(text, index) {
    var el = document.createElement('div');
    el.className = 'tag';
    var label = document.createElement('span');
    label.textContent = text;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tag-remove';
    btn.setAttribute('aria-label', 'Remove ' + text);
    btn.textContent = '✕';
    btn.setAttribute('data-i', String(index));
    el.appendChild(label);
    el.appendChild(btn);
    return el;
  }

  function renderTags() {
    tagsWrap.querySelectorAll('.tag').forEach(function(t) { t.remove(); });
    tags.forEach(function(tag, i) {
      tagsWrap.insertBefore(buildTagEl(tag, i), tagInput);
    });
    keywordsHidden.value = tags.join(',');
  }

  tagsWrap.addEventListener('click', function(e) {
    var removeBtn = e.target.closest('.tag-remove');
    if (removeBtn) {
      tags.splice(Number(removeBtn.getAttribute('data-i')), 1);
      renderTags();
    } else {
      tagInput.focus();
    }
  });

  tagInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      var val = tagInput.value.trim();
      if (val && !tags.includes(val)) { tags.push(val); renderTags(); }
      tagInput.value = '';
    }
    if (e.key === 'Backspace' && !tagInput.value && tags.length) {
      tags.pop(); renderTags();
    }
  });

  // Form submit — require at least one keyword
  document.getElementById('signup-form').addEventListener('submit', function(e) {
    var banner = document.getElementById('error-banner');
    if (tags.length === 0) {
      e.preventDefault();
      banner.textContent = 'Please add at least one keyword to track.';
      banner.classList.add('visible');
      tagsWrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
      banner.classList.remove('visible');
    }
  });
</script>

</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add app/static/signup.html
git commit -m "feat: add signup.html with Obsidian Momentum design"
```

---

### Task 7: End-to-end smoke test

- [ ] **Step 1: Start server**

```bash
cd /Users/yeganehkhabbazian/Projects/Product_manager_app/trendlens
source .venv/bin/activate
uvicorn main:app --reload
```

- [ ] **Step 2: Verify landing page CTAs**

Open `http://localhost:8000/landing.html` — "Get Started" and "Start Researching" must navigate to `/signup.html`.

- [ ] **Step 3: Verify signup flow**

Open `http://localhost:8000/signup.html`, fill all fields, add 2–3 keywords, submit. Should redirect to `http://localhost:8000/`.

- [ ] **Step 4: Verify domains were seeded**

```bash
curl -s http://localhost:8000/domains | python3 -m json.tool
# Should list the keywords entered during signup as tracked domains
```

- [ ] **Step 5: Verify duplicate email rejected**

Submit the signup form again with the same email. Should return HTTP 400 with "Email already registered."

- [ ] **Step 6: Commit any fixes**

```bash
git add -p
git commit -m "fix: e2e smoke test corrections"
```
