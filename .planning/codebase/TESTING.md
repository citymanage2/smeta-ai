# Testing Patterns

**Analysis Date:** 2026-03-17

## Test Framework

**Runner:**
- pytest (Python backend)
- No frontend testing framework configured

**Config:**
- `backend/tests/` directory structure for test organization
- No pytest.ini or setup.cfg found - using defaults
- Test discovery: standard pytest pattern (`test_*.py`)

**Run Commands:**
```bash
# Backend tests
pytest                    # Run all tests
pytest -v               # Verbose output
pytest backend/tests/   # Run specific test directory
```

## Test File Organization

**Location:**
- Backend: Co-located in separate `backend/tests/` directory (not alongside source)
- Frontend: No test files found

**Naming:**
- Test files: `test_*.py` pattern
- Test functions: `test_*` prefix
- Example: `backend/tests/test_basic.py` with functions like `test_imports()`, `test_hash_password()`

**Structure:**
```
backend/
├── app/
│   ├── config.py
│   ├── models/
│   ├── routers/
│   └── services/
├── tests/
│   ├── __init__.py
│   └── test_basic.py          # Current test suite
```

## Test Structure

**Suite Organization:**
```python
# backend/tests/test_basic.py pattern
def test_imports():
    """Verify core modules can be imported."""
    from app.config import settings
    assert settings.JWT_ALGORITHM == "HS256"
    assert settings.MAX_FILE_SIZE_MB == 20
```

**Patterns:**
- **Setup:** Direct imports within test function or via fixtures
- **Teardown:** Implicit cleanup via pytest fixtures (not used in current tests)
- **Assertion:** Direct `assert` statements with pytest
- **Documentation:** Docstring per test describing purpose

**Current Test Examples:**
- `test_imports()` - Verify module loading and configuration
- `test_hash_password()` - Cryptographic utility testing
- `test_create_access_token()` - JWT token generation and verification
- `test_normalize_text()` - String normalization for Russian text
- `test_parse_xlsx_empty()` - Excel file parsing with minimal data
- `test_generate_list()` - Excel list generation output validation
- `test_generate_smeta()` - Excel smeta generation
- `test_parse_xml()` - XML parsing validation

## Mocking

**Framework:** Not extensively used

**Patterns:**
- Minimal mocking observed in current tests
- Direct function calls preferred where possible
- Test isolation achieved through separate test data (BytesIO workbooks, in-memory data)

**What to Mock:**
- External API calls (Claude API in `claude_service`)
- Network requests beyond local testing
- File system operations that shouldn't persist

**What NOT to Mock:**
- Database calls for integration tests (test against real DB in isolated environment)
- Core utility functions (hash_password, normalize_text should be tested directly)
- Authentication flows that need real JWT validation

## Fixtures and Factories

**Test Data:**
- In-memory objects created within test functions
```python
# Example from test_basic.py
def test_parse_xlsx_empty():
    import io
    import openpyxl
    from app.utils.file_parser import parse_xlsx

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Test"
    ws["A1"] = "Наименование"
    ws["B1"] = "Количество"
    ws["A2"] = "Бетон М200"
    ws["B2"] = 10

    buf = io.BytesIO()
    wb.save(buf)
    result = parse_xlsx(buf.getvalue())
    assert "Наименование" in result
    assert "Бетон М200" in result
```

**Location:**
- No separate fixtures file - fixtures created inline in test_basic.py
- Opportunity to extract to `conftest.py` for reuse

## Coverage

**Requirements:** Not enforced

**Current Coverage:**
- Limited: Only 9 test cases for entire backend (basic smoke tests)
- No frontend tests
- Gaps in service layer testing (price_service, excel_service only partially tested)
- No endpoint integration tests

**View Coverage:**
```bash
# No coverage measurement configured
# To add coverage:
pytest --cov=app backend/tests/
pytest --cov-report=html backend/tests/  # Generate HTML report
```

## Test Types

**Unit Tests:**
- Scope: Individual functions and utilities
- Approach: Test utility functions in isolation (hash_password, verify_password, normalize_text)
- Location: `backend/tests/test_basic.py`
- Example: `test_hash_password()` tests bcrypt hashing and verification

**Integration Tests:**
- Scope: Component interaction (parsing Excel/XML, generating output)
- Approach: Test file parsing and generation together with real data structures
- Location: `backend/tests/test_basic.py` (parse_xlsx, generate_list, generate_smeta)
- Example: `test_parse_xlsx_empty()` tests parsing and validates parsed output

**E2E Tests:**
- Framework: Not implemented
- Could add: FastAPI TestClient for endpoint testing, browser automation for UI testing
- Missing: End-to-end task workflow testing (create task → process → retrieve results)

## Common Patterns

**Async Testing:**
- Current tests are synchronous
- Backend service functions are async (FastAPI async handlers)
- Need to add: `pytest-asyncio` and `@pytest.mark.asyncio` for async function testing

**Error Testing:**
```python
# Pattern to add: Test error conditions
def test_hash_password_empty_string():
    """Hash empty string should still produce valid hash."""
    from app.utils.auth import hash_password
    hashed = hash_password("")
    assert hashed != ""
    assert len(hashed) > 0

def test_verify_token_invalid():
    """Invalid token should raise HTTPException."""
    import pytest
    from fastapi import HTTPException
    from app.utils.auth import verify_token

    with pytest.raises(HTTPException):
        verify_token("invalid.token.here")
```

## Frontend Testing

**Current State:**
- No test framework configured
- No test files found
- Dependencies do not include testing libraries (no @testing-library/react, vitest, or jest)

**Recommended Setup for Future:**
- Framework: Vitest (lightweight, modern, integrates with Vite)
- Component testing: @testing-library/react for component testing
- Run commands to add:
  ```bash
  npm install --save-dev vitest @testing-library/react @testing-library/user-event
  ```

## Gap Analysis

**High Priority Testing Gaps:**
- No API endpoint testing (async endpoint handlers need TestClient)
- No Claude API service testing (should mock external API)
- No file upload workflow testing (end-to-end form → upload → task creation)
- No authentication flow testing (login endpoint, token validation)
- No database transaction testing
- No error handling path testing (invalid files, oversized files, network errors)

**What's Well Tested:**
- Utility functions (password hashing, text normalization)
- Basic file parsing (XLSX, XML)
- Output generation (Excel file creation)

---

*Testing analysis: 2026-03-17*
