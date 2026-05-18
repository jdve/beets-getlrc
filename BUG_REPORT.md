# Beets-GetLrc: Detailed Bug Report & Fixes

## 🔴 CRITICAL ISSUES FOUND

### Issue #1: No Worker Limit Validation
**Severity:** HIGH  
**File:** `__init__.py:444` (in `command()` method)  
**Problem:** Users can set `workers` to extremely high values (1000+) causing:
- Thread pool resource exhaustion
- Memory pressure
- System slowdown or crash

**Current Code:**
```python
workers = opts.workers if getattr(opts, 'workers', None) is not None else self.config['workers'].get(int)
# No validation! Users can pass workers=1000, workers=999999, etc.
```

**Fix:** Add reasonable bounds checking (recommend 1-64 workers).

---

### Issue #2: Import Progress Not Displayed
**Severity:** HIGH  
**File:** `__init__.py:384` (in `import_task_done()` method)  
**Problem:** When items are imported, users see NO progress indication:
- Queue is processed silently after all import prompts
- Users have no indication that lyrics are being fetched
- Appears frozen/unresponsive

**Current Code:**
```python
def import_task_done(self, lib, task, **kwargs):
    # ... collect items ...
    # Process items WITHOUT any progress display
    if workers > 1:
        def run(item):
            try:
                self.fetch_lrc(item, force=force, quiet=False)  # quiet=False but progress not shown
```

**Fix:** Create and display progress bar during import processing, similar to CLI.

---

### Issue #3: Incomplete Path Normalization in item_moved()
**Severity:** MEDIUM  
**File:** `__init__.py:418-430` (in `item_moved()` method)  
**Problem:** Path normalization doesn't fully handle beets' bytestring_path encoding:
- Assumes `fspath()` works with bytes, but beets uses custom encoding
- No explicit error handling for encoding mismatches
- Doesn't validate that source/destination are not None

**Current Code:**
```python
source_path = _os.fspath(source)
if isinstance(source_path, (bytes, bytearray)):
    source_path = source_path.decode('utf-8', 'surrogateescape')
# This could fail if source is None or invalid
```

**Fix:** Add explicit None checks and use displayable_path() for consistency.

---

### Issue #4: Race Condition - LRC Created After item_moved Event
**Severity:** MEDIUM  
**File:** `__init__.py:384-408` (timing issue between `import_task_done` and `item_moved`)  
**Problem:** If file move happens during or immediately after LRC fetch:
1. `fetch_lrc()` writes LRC to location A
2. Beets moves audio file from A to B (triggers `item_moved`)
3. LRC might not exist yet, or be written after move attempt

**Fix:** This is hard to fix in the plugin itself; document the race condition and ensure atomic writes.

---

### Issue #5: Progress Output Inconsistency Between CLI and Import
**Severity:** MEDIUM  
**File:** `__init__.py:384` vs `__init__.py:459` (different code paths)  
**Problem:** Visual output is completely different:
- **CLI path:** Shows progress bar, item count, colors, stats
- **Import path:** Silent operation, no feedback to user

**Fix:** Unify progress display logic for both paths.

---

### Issue #6: No Worker Bounds in import_task_done()
**Severity:** MEDIUM  
**File:** `__init__.py:384-415` (in `import_task_done()` method)  
**Problem:** import task doesn't validate worker count like command() does:
- Could create unlimited worker threads during import
- No upper bound checking

**Fix:** Apply same worker validation/bounds to import path.

---

### Issue #7: Color Code Leakage in Progress Prefix
**Severity:** LOW  
**File:** `__init__.py:122-131` (in `Progress.prefix()` method)  
**Problem:** ANSI color codes might not properly reset if progress is interrupted:
- Prefix is generated each time but reset code is at the end
- If output is truncated, color codes could remain "active"

**Current Code:**
```python
return f"{c.BOLD}[{current:04d}/{total:04d}] [{bar}] {percent:3d}% {self._format_elapsed(elapsed)}{c.RESET} "
# If this gets cut off mid-line, RESET won't be printed
```

**Fix:** Less critical, but document that full prefix should always be printed.

---

### Issue #8: Item Moved Not Notified to User During Large Operations
**Severity:** LOW  
**File:** `__init__.py:429` (in `item_moved()` method)  
**Problem:** Sidecar movement is only logged at DEBUG level:
- Users don't see which files are being moved during `beet move`
- Silent operation even with verbose/quiet flags

**Fix:** Add INFO-level logging for sidecar moves.

---

## 📋 Summary of Required Fixes

1. ✅ Add worker count bounds (1-64, configurable with warning)
2. ✅ Show progress during import
3. ✅ Improve path normalization in item_moved()
4. ✅ Unify progress display between CLI and import
5. ✅ Add worker bounds to import_task_done()
6. ✅ Document item_moved race condition
7. ✅ Add visible logging for sidecar moves
8. ✅ Add explicit None checks for paths
