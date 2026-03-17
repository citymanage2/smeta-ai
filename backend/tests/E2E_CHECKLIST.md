# E2E Post-Deployment Verification Checklist

**Purpose:** Step-by-step manual verification of all critical user flows after deployment.
**When to use:** After every production deployment or environment change.
**Prerequisites:** Access to the deployed frontend URL and backend URL. Know the user password and admin password (set via environment variables `USER_PASSWORD` and `ADMIN_PASSWORD`; defaults are `user123` and `admin123`).

**Legend:**
- `{BACKEND_URL}` — e.g., `https://smeta-ai-backend.onrender.com`
- `{FRONTEND_URL}` — e.g., `https://smeta-ai.onrender.com`

---

## Section 1: Environment Verification

- [ ] **1.1** Open `{BACKEND_URL}/health` in a browser or run:
  ```
  curl {BACKEND_URL}/health
  ```
  **Expected:** HTTP 200 with JSON body `{"status": "ok", "service": "Smeta AI"}`

- [ ] **1.2** Open `{FRONTEND_URL}` in a browser.
  **Expected:** Login page loads (input field for password, login button visible). No console errors in DevTools.

- [ ] **1.3** Open `{FRONTEND_URL}/admin` directly in the browser (without navigating from login first).
  **Expected:** Automatically redirected to the login page — SPA routing is working. The page does NOT show "Not Found" or a blank white screen.

- [ ] **1.4** Open `{BACKEND_URL}/docs` in a browser.
  **Expected:** Swagger UI loads, listing all endpoints (auth, tasks, results, admin).

---

## Section 2: User Authentication

- [ ] **2.1** On the login page, enter the **user password** (value of `USER_PASSWORD` env var) and click the login button.
  **Expected:** Redirected to the task creation page. The role indicator in the UI shows "Пользователь" (not "Администратор").

- [ ] **2.2** Open browser DevTools → Application tab → Local Storage → `{FRONTEND_URL}`.
  **Expected:** An auth token is present in Local Storage (key contains "token" or "auth").

- [ ] **2.3** Refresh the page while on the task creation page.
  **Expected:** Still on the task creation page — session persists across page refreshes.

- [ ] **2.4** Clear Local Storage (DevTools → Application → Local Storage → Right-click → Clear) and refresh.
  **Expected:** Redirected back to the login page — expired/missing session is detected.

---

## Section 3: Admin Authentication

- [ ] **3.1** Log in with the **admin password** (value of `ADMIN_PASSWORD` env var).
  **Expected:** Login succeeds and the role indicator shows "Администратор" — NOT "Пользователь". (This verifies BUG-03 is resolved: the JWT `role` field is correctly set to `"admin"` and the frontend reads it correctly.)

- [ ] **3.2** After logging in as admin, navigate to `{FRONTEND_URL}/admin`.
  **Expected:** Admin panel loads with a task history table. The page does NOT redirect back to login.

- [ ] **3.3** While logged in as user (not admin), attempt to call the admin API directly:
  ```
  curl -H "Authorization: Bearer {USER_TOKEN}" {BACKEND_URL}/admin/tasks
  ```
  **Expected:** HTTP 403 Forbidden — non-admin users cannot access admin endpoints.

---

## Section 4: Task Creation and Processing

- [ ] **4.1** Log in as user, navigate to the task creation page.
  **Expected:** Form is visible with task type selector and file upload area.

- [ ] **4.2** Select task type **"Список работ из ТЗ"** (LIST_FROM_TZ) from the dropdown.
  **Expected:** Task type is selected without error.

- [ ] **4.3** Upload a small PDF file (any construction document, under 1 MB).
  **Expected:** File appears in the upload area with its filename displayed. No error about unsupported format.

- [ ] **4.4** Click the Submit / Create task button.
  **Expected:** The app navigates to a task status page. The URL contains the task ID (a UUID, e.g., `/task/550e8400-e29b-41d4-a716-446655440000/status`). The response from `POST {BACKEND_URL}/tasks` returned `{"task_id": "...", "status": "pending"}`.

- [ ] **4.5** Watch the status polling on the task status page.
  **Expected:** Progress messages appear (e.g., "Анализ документов...", "Составление сметы..."). Status transitions from `pending` → `processing` → `completed` (or `failed` if AI service is unavailable). The UI updates without manual refresh — polling is working.

- [ ] **4.6** If task status becomes `completed`: a download button appears.
  **Expected:** Button is visible and clickable. Task did not stay in `pending` forever (polling worked correctly).

---

## Section 5: Task Status Polling

- [ ] **5.1** Open browser DevTools → Network tab, then submit a new task (or navigate to an existing in-progress task).
  **Expected:** Repeated GET requests appear in the Network tab at regular intervals.

- [ ] **5.2** Inspect one of the polling requests.
  **Expected:** Request URL is `{BACKEND_URL}/tasks/{taskId}/status`. Method is GET. Request includes `Authorization: Bearer ...` header.

- [ ] **5.3** Inspect the polling response.
  **Expected:** HTTP 200. Response body contains `status` field (one of: `pending`, `processing`, `completed`, `failed`) and `progress_message` field (may be `null` when pending). Example:
  ```json
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "task_type": "LIST_FROM_TZ",
    "status": "processing",
    "progress_message": "Анализ документов...",
    "error_message": null,
    "created_at": "2026-03-18T10:00:00",
    "updated_at": "2026-03-18T10:00:05"
  }
  ```

- [ ] **5.4** Navigate away from the task status page (e.g., go back to task creation) and then navigate back using the browser Back button.
  **Expected:** Task status page re-loads correctly and resumes polling. No blank page or stale data.

---

## Section 6: Result Download

- [ ] **6.1** After a task completes, click the Download Result button.
  **Expected:** A file download dialog appears in the browser.

- [ ] **6.2** Inspect the downloaded file.
  **Expected:** Filename contains Russian characters if applicable (Content-Disposition header uses `filename*=UTF-8''...` encoding). File is not 0 bytes.

- [ ] **6.3** Open the downloaded file (Excel or other format).
  **Expected:** File opens without corruption errors. Contains generated cost estimate data — not empty, not a placeholder.

- [ ] **6.4** Verify via API that the result endpoint works:
  ```
  curl -H "Authorization: Bearer {USER_TOKEN}" {BACKEND_URL}/tasks/{taskId}/results
  ```
  **Expected:** HTTP 200 with a JSON array listing result files:
  ```json
  [{"file_id": 1, "file_name": "smeta_result.xlsx", "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}]
  ```
  Then download via: `GET {BACKEND_URL}/results/{file_id}/download`

---

## Section 7: Admin Panel — Task History

- [ ] **7.1** Log in as admin, navigate to `{FRONTEND_URL}/admin`.
  **Expected:** Task history table is visible with at least the tasks submitted during this test.

- [ ] **7.2** Verify table columns are present: submission date/time, task type, status.
  **Expected:** All tasks submitted during testing appear in the list, sorted by date descending (newest first).

- [ ] **7.3** If more than 20 tasks exist in the database: verify pagination controls are visible and the "Next page" button loads the next 20 tasks.
  **Expected:** Pagination works — page 2 shows different tasks than page 1. (Uses `GET /admin/tasks?page=2&limit=20`.)

- [ ] **7.4** Click on a completed task row to expand task details.
  **Expected:** Conversation transcript (chat_history) is displayed — showing the AI interaction messages. Task details include input file names, task type, and timestamps.

---

## Section 8: Admin Panel — File Downloads

- [ ] **8.1** In the admin task history, find a task that has input files uploaded (any task submitted with a PDF).
  **Expected:** The task row or detail view shows the original file name.

- [ ] **8.2** Click the button to download the original uploaded file (input file re-download).
  **Expected:** The original PDF or other file downloads successfully. File is not corrupted (same byte count as originally uploaded). This calls `GET {BACKEND_URL}/admin/tasks/{taskId}/download-input/0`.

- [ ] **8.3** For a completed task, download the result file from the admin panel.
  **Expected:** Generated Excel result downloads correctly. This confirms admin can retrieve both input and output files for any task.

---

## Section 9: Error Handling

- [ ] **9.1** On the login page, enter an incorrect password (e.g., "wrongpassword") and click login.
  **Expected:** Error message appears: "Неверный пароль". No redirect occurs. The backend returns HTTP 401.

- [ ] **9.2** Try to upload a `.gsn` file (GrandSmeta format) when creating a task.
  **Expected:** Error message appears explaining that `.gsn` is not supported and instructing the user to export to XML: "Формат .gsn не поддерживается. Экспортируйте смету в XML: Файл → Экспорт → XML". Upload is rejected with HTTP 415.

- [ ] **9.3** Try to upload a file larger than 20 MB.
  **Expected:** Error message appears mentioning the file size limit. Upload is rejected with HTTP 413.

- [ ] **9.4** Navigate to a task status page with a non-existent task ID (e.g., `{FRONTEND_URL}/task/nonexistent-id/status`).
  **Expected:** Graceful error state displayed — not a blank white page or crash. The backend returns HTTP 404 for `GET /tasks/nonexistent-id/status`.

- [ ] **9.5** Submit a task with no files attached (if task type requires files).
  **Expected:** Appropriate error message is shown. No crash or unhandled error in the console.

---

## Section 10: Cross-Browser and Edge Cases

- [ ] **10.1** Repeat the login flow (Section 2) in both **Chrome** and **Firefox**.
  **Expected:** Identical behavior in both browsers. No browser-specific rendering issues.

- [ ] **10.2** Upload a file near the 20 MB size limit (e.g., 18–19 MB PDF).
  **Expected:** File uploads successfully and task is created (does not get rejected as too large). Processing may take longer for large files.

- [ ] **10.3** Open the app on a mobile viewport (use Chrome DevTools device toolbar, set to "iPhone 14" or similar 390px width).
  **Expected:** Layout is readable and usable on mobile — no overflowing elements, buttons are tappable, text is not cut off.

- [ ] **10.4** Verify that navigating to `{FRONTEND_URL}/admin` without being logged in (fresh incognito session) redirects to login.
  **Expected:** Redirected to login page. The admin panel content does NOT render even momentarily before redirect.

- [ ] **10.5** After completing a task, send a follow-up chat message using the clarification input (if available in the UI).
  **Expected:** Message is accepted, task status resets to `pending`, and processing restarts. The backend `POST /tasks/{taskId}/message` returns `{"task_id": "...", "status": "pending", "message": "Сообщение принято, задача перезапущена"}`.

---

## Sign-Off

| Tester | Date | Environment | All Sections Pass? | Notes |
|--------|------|-------------|-------------------|-------|
|        |      |             |                   |       |

---
*Checklist version: 1.0 — Created for smeta-ai v1.0*
*Covers: Phase 1 (BUG-01 API base URL, BUG-02 SPA routing, BUG-03 admin role), Phase 2 (admin panel, file downloads, pagination, chat transcript), Phase 3 (manual post-deployment verification)*
