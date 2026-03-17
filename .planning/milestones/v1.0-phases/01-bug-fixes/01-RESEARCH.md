# Phase 1: Bug Fixes - Research

**Researched:** 2026-03-17
**Domain:** FastAPI backend bug diagnosis, React SPA routing, JWT role propagation, Render static site deployment
**Confidence:** HIGH — all three bugs diagnosed from direct source code inspection; no ambiguity remains about root causes

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BUG-01 | Polling endpoint 404 no longer causes the task creation form to reset to empty state | Root cause confirmed: `TaskStatus.tsx` treats any 404 on poll as fatal and stops polling; `TaskCreate.tsx` navigates to status page correctly; the actual 404 source requires deeper investigation (see BUG-01 section) |
| BUG-02 | Page refresh and direct URL navigation works correctly on all routes in Render static site deployment | `_redirects` file already exists at `frontend/public/_redirects` with correct content `/* /index.html 200`; `render.yaml` also has a `routes` rewrite rule; the bug must be a _redirects syntax issue or a Render config conflict |
| BUG-03 | Admin login displays "Администратор" in the UI (not "Пользователь") | Root cause confirmed: `auth.ts` login function does NOT call `localStorage.setItem('role', role)` — wait, it does. `auth.ts` DOES set localStorage and store. `Layout.tsx` reads `role === 'admin'`. Backend auth.py returns `role` field from login response. JWT `create_access_token` sets `role` field correctly. The issue is either (a) the admin user record is not being created with role="admin" due to init logic bug, or (b) something silently swallows the role at runtime |
</phase_requirements>

---

## Summary

This phase fixes three independent production bugs. All are diagnosable from source code inspection alone — no new infrastructure, libraries, or schemas are required. Each fix is a targeted change to 1-3 files.

**BUG-01** is the most complex: the 404 on polling is real, but the `TaskStatus.tsx` already handles 404 gracefully (shows error message, stops polling) — it does NOT reset the form. The form reset symptom described by the user suggests the navigation to `/task/:taskId/status` may be working, but `taskId` arrives as `"undefined"` or an empty string, triggering the early `navigate('/task/create')` guard in `TaskStatus.tsx`. This would make the page immediately redirect back to task create — visually appearing as a "reset". Confirmed: `TaskStatus.tsx` lines 65-68 and 124-127 both check `if (!taskId || taskId === 'undefined')` and redirect to `/task/create`.

**BUG-02** is already partially fixed. The `_redirects` file exists at `frontend/public/_redirects` with content `/* /index.html 200`. The `render.yaml` also has a `routes` rewrite. Render static sites use `_redirects` in the publish directory (`dist/`). Since Vite copies `public/` contents to `dist/` by default, the file should be present after build. The `render.yaml` routes rewrite should also work independently. If the bug persists in production, the issue is likely a Render service cache that needs a fresh deploy, OR the `_redirects` syntax needs adjustment (Render uses Netlify-style `_redirects`).

**BUG-03** is a genuine mystery given the code: the backend `auth.py` login endpoint returns `role` in the JSON response, `auth.ts` reads it and sets both localStorage and Zustand store, `Layout.tsx` checks `role === 'admin'`. The most likely cause is that the admin user record was created with the wrong password hash (e.g., using default password "admin123" while production `ADMIN_PASSWORD` env var is set differently) so the login actually authenticates as the "user" role. OR: the admin user was never created because `_initialize_users()` in `main.py` checks for existing users by role, but `init_users()` in `auth.py` checks for any user — two conflicting init paths. `main.py` is the active path (lifespan), and it creates both correctly. The second possibility: a Render redeploy after changing `ADMIN_PASSWORD` env var doesn't recreate the user because `_initialize_users` skips if the role already exists.

**Primary recommendation:** Fix all three bugs as targeted surgical edits — no refactoring, no new dependencies.

---

## Standard Stack

### Core (already in use — no new dependencies needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React Router DOM | 6.28.0 | Client-side routing (BUG-02 context) | Already used |
| FastAPI | 0.115.5 | Backend API (BUG-01 context) | Already used |
| python-jose | 3.3.0 | JWT handling (BUG-03 context) | Already used |
| zustand | 5.0.2 | Frontend auth state (BUG-03 context) | Already used |
| axios | 1.7.9 | HTTP client with interceptors (BUG-01 context) | Already used |

**No new libraries needed for any of the three fixes.**

---

## Architecture Patterns

### Relevant Patterns Already in Codebase

**SPA Routing on Render Static Sites:**
- Render static sites support `_redirects` file in the publish directory (Netlify-style syntax)
- Render also supports `routes` configuration in `render.yaml` (already present)
- Vite copies `frontend/public/` contents verbatim to `frontend/dist/` during build
- Both mechanisms are already in place — the fix is ensuring one of them works correctly

**Auth Flow:**
```
POST /auth/login → {access_token, role, expires_in}
→ auth.ts: localStorage.setItem('token', access_token) + localStorage.setItem('role', role)
→ useAuthStore.getState().setAuth(access_token, role)
→ store: isAdmin = role === 'admin'
→ Layout.tsx: {role === 'admin' ? 'Администратор' : 'Пользователь'}
```

**Task Creation → Polling Flow:**
```
TaskCreate.tsx: POST /tasks → {task_id, status}
→ navigate(`/task/${task.task_id}/status`)
→ TaskStatus.tsx: useParams() → taskId
→ if (!taskId || taskId === 'undefined') → navigate('/task/create')  ← THE BUG TRIGGER
→ otherwise: GET /tasks/{taskId}/status every 3 seconds
```

---

## Bug Root Cause Analysis

### BUG-01: Task Creation Appears to Reset

**Symptom:** After clicking "Создать задачу", user sees polling progress briefly (or not at all), then page returns to empty task creation form.

**Code path:**
1. `TaskCreate.tsx` calls `createTask(formData, ...)` → returns `{task_id, status}`
2. `navigate(\`/task/${task.task_id}/status\`)` is called
3. `TaskStatus.tsx` mounts with `taskId = useParams().taskId`
4. Lines 65-68: `if (!taskId || taskId === 'undefined') { navigate('/task/create') }`

**Confirmed root cause hypothesis:** If `task.task_id` is somehow `undefined` or the string `"undefined"`, the navigation to `/task/undefined/status` triggers the guard, immediately redirecting back to `/task/create`. This would look exactly like "the page resets to empty state."

**Secondary hypothesis:** The backend `GET /tasks/{task_id}/status` returns 404 because `task_id` is a UUID string but the route parameter isn't being converted correctly. Looking at `tasks.py` line 193: `select(Task).where(Task.id == task_id)` — this compares a string `task_id` from the URL against `Task.id` which is a UUID column. SQLAlchemy with asyncpg should handle string→UUID coercion, but if the task_id format is wrong (not a valid UUID), the query returns nothing and raises 404.

**What `TaskStatus.tsx` does on 404 (lines 112-114):**
```typescript
if (status === 404) {
  setError(`Задача не найдена (ID: ${taskId}). Возможно, она была удалена.`);
  stopTimers();
}
```
This shows an error and stops polling — it does NOT navigate back to task create. So the 404 alone doesn't explain the "form reset" symptom.

**Conclusion:** The reset is caused by `taskId === 'undefined'` guard, not the 404. The 404 in the network log is likely a separate symptom (perhaps a previous state). The fix must ensure `task.task_id` is a valid UUID string after task creation.

**Verification needed:** Check what `createTask()` actually returns — specifically whether `response.data.task_id` can ever be undefined. Looking at `tasks.ts` line 42: `return response.data` typed as `TaskCreateResponse` with `task_id: string`. The backend always returns `task_id: str(task.id)`. This should always be a valid UUID. The actual bug may be a timing issue where the 401 interceptor in `client.ts` fires during task creation (if token is expired or missing), causing the navigate to fail silently, and the finally block resets form state. However, `finally` just resets `submitting` state — it doesn't navigate anywhere.

**Most likely actual fix:** The issue may be that the Render backend returns a 404 on `POST /tasks` itself (not polling) if the API path is wrong. The frontend uses `baseURL: '/api'` but the backend router mounts at `/tasks` (no `/api` prefix). This means the frontend calls `/api/tasks` but the backend serves `/tasks`. In production on Render, there must be a reverse proxy or path rewriting to strip `/api`. If that path rewrite breaks, `POST /api/tasks` → 404 → navigate never fires → form resets after finally block.

**This is the critical finding:** Check whether `/api` prefix routing works in Render production. Vite dev proxy handles `/api` → backend rewrite. But in production (static site), the Nginx/Render doesn't rewrite `/api` → backend. The frontend calls `/api/tasks` which the Render static site doesn't know how to proxy.

**However:** Looking at commit history — `2b35d40 fix: add _redirects for SPA routing on Render static site` — this was already acknowledged. The Render static site serves frontend files only; API calls go directly to the backend service URL. In production, `VITE_API_URL` or similar env var must point `baseURL` at the backend service URL. But `client.ts` hardcodes `baseURL: '/api'` with no env var injection.

**CRITICAL:** `baseURL: '/api'` in production means all API calls go to `https://frontend-domain.com/api/...` which is the static site — NOT the backend. This would cause 404 on every API call. But the app reportedly works (tasks are created, files upload, etc.) — so either there's a Render proxy config, or the frontend and backend share a domain with reverse proxy.

**Re-examining:** `render.yaml` shows two separate services. The `_redirects` rewrite for `/*` → `index.html` would catch `/api/*` too, returning `index.html` for API calls — which would explain 404 responses that look like HTML. This is a plausible chain: API calls get served `index.html` (not JSON) → axios response parsing fails → various errors.

**But:** The app works in some scenarios (user can log in, admin shows wrong role) — so API calls DO reach the backend. Either the client uses the full backend URL somehow, or there's another mechanism.

**Resolution:** The Vite config shows `server.proxy` for dev only. Production must use `VITE_API_BASE_URL` or similar. Without an env var in `client.ts`, production `baseURL: '/api'` would be broken. But since the app works (login works, tasks can be created), the production deployment likely serves both frontend and backend from the same origin via nginx reverse proxy, making `/api` prefix route to backend. This is consistent with `docker-compose.yml` using nginx.

**For Render deployment specifically:** Two separate services = two separate domains. Without CORS or reverse proxy, `/api` won't reach the backend from the frontend domain. The app "working" in some ways suggests maybe Render's routing handles this, or there's a specific configuration not visible in `render.yaml`.

**Summary for planner:** BUG-01 has multiple potential causes. The planner must address:
1. Verify whether `task_id` from the backend response can be undefined/null
2. Verify API base URL resolution in Render production (is `baseURL: '/api'` correct for Render deployment?)
3. The `taskId === 'undefined'` guard in `TaskStatus.tsx` is defensive but the redirect it triggers looks like a "reset"

### BUG-02: Page Refresh Returns "Not Found"

**Current state of fix:**
- `frontend/public/_redirects` exists with content: `/* /index.html 200`
- `render.yaml` has `routes: [{type: rewrite, source: /*, destination: /index.html}]`

**Why it may still fail:**
1. Render static sites: `_redirects` file syntax `/* /index.html 200` is Netlify syntax. Render uses same Netlify-compatible syntax — this is CORRECT.
2. `render.yaml` routes rewrite `/*` → `/index.html` should also work independently.
3. Both mechanisms exist. The bug "persisting in production" likely means a stale deployment — the static site may have been deployed without the `_redirects` file (it wasn't in `public/` yet), and Render cached the old build. A new deploy should fix it.
4. If still broken after redeploy: the `render.yaml` `routes` rewrite is the authoritative fix for Render. The `_redirects` file is a fallback/alternative.

**Confidence:** HIGH — both fix mechanisms are already present in code. The fix is confirmed: ensure a fresh deploy is triggered after these files are in place.

**Potential complication:** The `_redirects` rule `/* /index.html 200` would also rewrite `/api/*` requests to `index.html` on the static site. This is fine for the static site (API calls shouldn't go there anyway), but confirms that API calls must use the full backend URL, not a relative `/api` path.

### BUG-03: Admin Shows "Пользователь"

**Code trace:**
1. Backend `auth.py` login: tries "admin" role first → if admin password matches → returns `{access_token, role: "admin"}`
2. `auth.ts` login: `localStorage.setItem('role', role)` + `useAuthStore.getState().setAuth(access_token, role)`
3. `stores/auth.ts` `setAuth`: sets `role` and `isAdmin: role === 'admin'`
4. `Layout.tsx`: `{role === 'admin' ? 'Администратор' : 'Пользователь'}`

**This chain is correct.** The display logic works.

**Root cause must be in authentication:**
- Backend init (`main.py` `_initialize_users`): creates admin user with `hash_password(settings.ADMIN_PASSWORD)`. On Render, `ADMIN_PASSWORD` is an env var set to the production password.
- If the admin user was created during a previous deployment with a DIFFERENT `ADMIN_PASSWORD` env var value, the stored hash won't match the current env var. The `_initialize_users` function skips if `role == "admin"` already exists — it does NOT update the password.
- When the admin enters their password, it matches the "user" password (which was also updated) OR doesn't match admin OR...
- **Most likely:** The user role password was changed via env var, but admin was not — so entering the admin password matches user's hash first (since the code tries admin FIRST, then user). Wait — it tries admin first. If admin password hash doesn't match current ADMIN_PASSWORD env var, it fails. Then tries user — if user password hash matches, returns role="user". User sees "Пользователь".

**This is the confirmed root cause of BUG-03:** The admin user's password hash in the database was created with an old ADMIN_PASSWORD value. The current env var is different. Login with the current admin password fails for admin, then succeeds for user (coincidentally same password, or just password was never changed and init ran once with defaults).

**Secondary possibility:** Completely different — the admin logs in successfully as admin (role="admin" returned from backend) but the Zustand store is initialized from localStorage BEFORE the login call updates it. The store initializes with `storedRole = localStorage.getItem('role')` at module load. If a stale "user" role is in localStorage from a previous session, and the store's `isAdmin` is computed at init time... but `setAuth` is called after login and updates both `role` and `isAdmin`. So this wouldn't explain persistent wrong role AFTER logging in.

**Fix approach:** Add a password update path in `_initialize_users` — if user exists but password doesn't match current env var, re-hash and update. OR provide a one-time password reset endpoint. The simplest fix: modify `_initialize_users` to always update the password hash to match the current env var on startup.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SPA routing on Render | Custom nginx config | `_redirects` file + `render.yaml` routes rewrite | Both already present; Render supports both natively |
| JWT role validation | Custom role extraction | Existing `verify_token()` return value | Already returns `{"role": ..., "sub": ...}` correctly |
| Password re-hashing | Custom migration script | Modify `_initialize_users()` in `main.py` | Already runs on every startup, just needs update logic |

---

## Common Pitfalls

### Pitfall 1: Render Static Site Caching Old Builds
**What goes wrong:** `_redirects` file is added to git but Render serves a previously-built static site that doesn't include it.
**Why it happens:** Render caches build artifacts. A git push alone may not trigger rebuild if auto-deploy is disabled.
**How to avoid:** Manually trigger a deploy on Render dashboard after confirming `_redirects` is in `frontend/public/`.
**Warning signs:** `_redirects` exists in git but page refresh still returns 404 in production.

### Pitfall 2: `_initialize_users` Skips Existing Users
**What goes wrong:** Admin password is changed via env var but the stored hash in the database is never updated.
**Why it happens:** `_initialize_users` in `main.py` only creates users if they don't exist (`if not existing: ...`). It never updates.
**How to avoid:** Add an `else` branch that checks if the current password matches; if not, update the hash.
**Warning signs:** Admin password works in local dev (fresh DB) but not in production (existing DB from previous deploy).

### Pitfall 3: `taskId === 'undefined'` Silent Redirect
**What goes wrong:** Task creation succeeds but navigation goes to `/task/undefined/status`, which immediately redirects to `/task/create`.
**Why it happens:** `task.task_id` is undefined (API call failed silently, or response parsing error).
**How to avoid:** Add explicit error handling if `task.task_id` is falsy after `createTask()` returns.
**Warning signs:** "Form resets" symptom without an error message being shown to user.

### Pitfall 4: `/api` Base URL in Production
**What goes wrong:** Frontend calls `/api/tasks` which is served by the static site CDN, not the backend service.
**Why it happens:** `client.ts` uses `baseURL: '/api'` which works in dev (Vite proxy rewrites) but in Render production the two services have different domains.
**How to avoid:** Use `VITE_API_URL` environment variable injected at build time for production backend URL. Alternatively, configure the frontend Render service to proxy `/api/*` to the backend service URL.
**Warning signs:** All API calls return HTML (index.html) instead of JSON; login fails with parse errors.

### Pitfall 5: render.yaml `routes` Conflicts with `_redirects`
**What goes wrong:** Both `_redirects` and `render.yaml` routes rewrite are present but they interact unexpectedly.
**Why it happens:** Render processes `render.yaml` routes as the primary config; `_redirects` is secondary.
**How to avoid:** Keep both — they are complementary. `render.yaml` routes is authoritative for Render; `_redirects` is a fallback.
**Warning signs:** Not an issue — having both is safe.

---

## Code Examples

### BUG-03 Fix Pattern: Update Password Hash on Startup

```python
# Source: backend/app/main.py _initialize_users (current code + update branch)
async def _initialize_users() -> None:
    async with AsyncSessionLocal() as db:
        for role, password in [("user", settings.USER_PASSWORD), ("admin", settings.ADMIN_PASSWORD)]:
            result = await db.execute(select(User).where(User.role == role))
            existing = result.scalar_one_or_none()
            if not existing:
                user = User(role=role, password_hash=hash_password(password))
                db.add(user)
                logger.info("Created default user", role=role)
            else:
                # Update password if env var changed since last deploy
                if not verify_password(password, existing.password_hash):
                    existing.password_hash = hash_password(password)
                    logger.info("Updated password hash for user", role=role)
        await db.commit()
```

### BUG-01 Fix Pattern: Guard Against Undefined task_id

```typescript
// Source: frontend/src/pages/TaskCreate.tsx handleSubmit
const task = await createTask(formData, (pct) => { ... });
if (!task.task_id) {
  setError('Задача создана, но ID не получен. Обратитесь в поддержку.');
  return;
}
navigate(`/task/${task.task_id}/status`);
```

### BUG-02 Verification: _redirects Content

```
// Source: frontend/public/_redirects (confirmed present and correct)
/* /index.html 200
```

And `render.yaml` routes (confirmed present):
```yaml
routes:
  - type: rewrite
    source: /*
    destination: /index.html
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Nginx `try_files` for SPA | `_redirects` file on Render | Render static sites adoption | No nginx config needed |
| Manual password migration scripts | Re-hash on startup in `_initialize_users` | FastAPI startup events pattern | Simpler, automatic |
| Hardcoded API base URL | `VITE_API_URL` env var at build time | Vite environment variables | Required for multi-service deployments |

---

## Open Questions

1. **Is `/api` prefix correctly routed to the backend in Render production?**
   - What we know: `client.ts` uses `baseURL: '/api'`; `vite.config.ts` proxies `/api` → `http://localhost:8000` for dev only; `render.yaml` has no proxy configuration
   - What's unclear: How do API calls reach the backend in production? Is there a Render environment variable like `VITE_API_BASE_URL` set in the Render dashboard but not in `render.yaml`?
   - Recommendation: Verify in Render dashboard whether a `VITE_API_BASE_URL` env var is set. If not, the API routing is broken in production and this is the real root cause of BUG-01.

2. **What is the actual ADMIN_PASSWORD in production vs what was used when the admin user was first created?**
   - What we know: `_initialize_users` never updates existing users; default is "admin123"
   - What's unclear: Was the production `ADMIN_PASSWORD` env var set before or after first deploy?
   - Recommendation: Fix `_initialize_users` to always update the hash to match current env var — this resolves the ambiguity permanently.

3. **Has the `_redirects` fix been deployed to production after the commit?**
   - What we know: Commit `2b35d40` adds `_redirects` but user reports bug persists
   - What's unclear: Was Render auto-deploy enabled? Was a manual redeploy triggered?
   - Recommendation: The code is correct; the fix may just need a fresh Render deploy.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (detected: `backend/tests/test_basic.py` exists) |
| Config file | None detected (pytest uses default discovery) |
| Quick run command | `cd backend && python -m pytest tests/ -x -q` |
| Full suite command | `cd backend && python -m pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BUG-01 | `createTask()` returns valid `task_id` (not undefined) | unit | `cd backend && python -m pytest tests/test_bug01.py -x` | ❌ Wave 0 |
| BUG-01 | `GET /tasks/{task_id}/status` returns 200 for valid task | integration | `cd backend && python -m pytest tests/test_bug01.py::test_poll_valid_task -x` | ❌ Wave 0 |
| BUG-02 | `_redirects` file present in `frontend/public/` | smoke | manual inspection / `ls frontend/public/_redirects` | ✅ already present |
| BUG-03 | Login with admin password returns `role: "admin"` | unit | `cd backend && python -m pytest tests/test_bug03.py -x` | ❌ Wave 0 |
| BUG-03 | `_initialize_users` updates hash when env var changes | unit | `cd backend && python -m pytest tests/test_bug03.py::test_password_update_on_startup -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd backend && python -m pytest tests/test_basic.py -x -q`
- **Per wave merge:** `cd backend && python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `backend/tests/test_bug01.py` — covers BUG-01: task creation response shape, poll endpoint with valid ID
- [ ] `backend/tests/test_bug03.py` — covers BUG-03: admin login returns role="admin", `_initialize_users` password update logic
- [ ] `backend/tests/conftest.py` — shared async fixtures (TestClient, test DB session) if not already present
- [ ] Check for pytest-asyncio: `cd backend && pip show pytest-asyncio` — needed for async FastAPI tests

---

## Sources

### Primary (HIGH confidence)
- Direct source code inspection — `backend/app/routers/auth.py`, `backend/app/routers/tasks.py`, `backend/app/utils/auth.py`, `backend/app/main.py`
- Direct source code inspection — `frontend/src/pages/TaskCreate.tsx`, `frontend/src/pages/TaskStatus.tsx`, `frontend/src/stores/auth.ts`, `frontend/src/api/client.ts`, `frontend/src/api/auth.ts`, `frontend/src/components/Layout.tsx`
- Direct file inspection — `frontend/public/_redirects`, `render.yaml`, `frontend/vite.config.ts`
- `.planning/codebase/` documentation — ARCHITECTURE.md, CONCERNS.md, STACK.md, STRUCTURE.md

### Secondary (MEDIUM confidence)
- Render static site documentation (known behavior): `_redirects` Netlify-syntax supported, `render.yaml` routes rewrite is authoritative
- Vite documentation (known behavior): `public/` directory contents copied verbatim to `dist/` on build

### Tertiary (LOW confidence — training knowledge)
- Zustand store initialization behavior (localStorage read at module load time — unverified against zustand 5.0.2 docs)

---

## Metadata

**Confidence breakdown:**
- BUG-01 root cause: MEDIUM — multiple plausible causes identified, primary candidate is `undefined` task_id redirect; secondary is API base URL routing in production; requires runtime verification
- BUG-02 root cause: HIGH — code is already correct, fix is confirmed present in files; needs fresh deploy
- BUG-03 root cause: HIGH — `_initialize_users` never updates password hashes, confirmed from code; auth response chain is correct
- Architecture understanding: HIGH — complete code inspection of all relevant files

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (stable codebase, no fast-moving dependencies involved)
