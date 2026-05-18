# Deep Bug Check Analysis

## 1. Worker Concurrency Issues

### Identified Issues:

#### A. Progress Increment Race Condition in Threaded Execution
**Location:** `command()` method, threaded execution path
**Issue:** When using multiple workers, the progress counter may not accurately track items, leading to display glitches or incorrect counts.

```python
def run(item):
    count = progress.increment() if progress else None  # Gets incremented value
    self.fetch_lrc(...)  # Long operation
    # If exception occurs, we DON'T increment again but count is already taken
```

**Problem:** The `count` is captured before `fetch_lrc()` completes. If an exception occurs, the progress counter is incremented elsewhere (in the exception handler), but the count passed to fetch_lrc is from before the operation. This can cause:
- Duplicate progress counts
- Skipped progress numbers
- Out-of-order output logging

#### B. Progress Bar Not Reset Between Operations
**Location:** `Progress` class initialization
**Issue:** `_start_time` is set once at initialization, not per batch. When processing multiple batches (import queue vs command line), the elapsed time calculation becomes meaningless.

#### C. Potential Deadlock in Progress Logging
**Location:** `Progress.log()` method
**Issue:** The `_pending` queue can grow unbounded if items complete significantly out of order. With many workers, this could consume memory or cause delays.

#### D. No Worker Limit Validation
**Location:** `command()` method
**Issue:** No upper limit on workers. Users could set `workers: 1000` and cause system resource exhaustion.

---

## 2. Sidecar File Movement Issues

### Identified Issues:

#### A. Incomplete Path Normalization
**Location:** `item_moved()` method
**Issue:** The method attempts to normalize bytes/string paths but doesn't handle all cases:
- `bytestring_path()` from beets returns bytes, but code tries to use `fspath()` which may not handle beets' encoding
- No validation that `source` and `destination` are not None

#### B. Missing Validation in `album_moved()`
**Location:** `album_moved()` method
**Issue:** 
- `album` object is never actually used (no type validation)
- If source doesn't exist but destination doesn't either, no error is reported
- `rglob()` could match unrelated files if extensions overlap

#### C. Race Condition: LRC File Created After Move
**Location:** Timing between `item_moved` and `fetch_lrc()`
**Issue:** If `beet move` happens immediately after `fetch_lrc()`, there's a narrow window where:
1. LRC file is written to old location
2. `item_moved` fires
3. LRC file is moved
4. But if fetch fails or is in progress, the LRC might not exist to move

#### D. No Sidecar Files Created for Items Without Fetch
**Location:** `item_moved()` and `album_moved()`
**Issue:** These only move existing sidecar files. If an item was never fetched (no LRC), nothing happens. Users expect sidecars created later to also follow moves.

---

## 3. Import Output Formatting Issues

### Identified Issues:

#### A. Progress Display Confusion During Import
**Location:** `import_task_done()` method
**Issue:**
- During import, there's NO progress display shown - items are processed silently after all prompts
- Users see nothing happen, making them think the plugin broke
- No indication of how many items are being processed
- Import queue is hidden from user

#### B. Mixed Progress Context
**Location:** `fetch_lrc()` and `import_task_done()`
**Issue:**
- Command-line execution shows full progress bar with prefix
- Import execution shows minimal output
- Visual consistency is broken: users don't know items are being processed during import

#### C. Color Reset Issues in Terminal
**Location:** `_print()` method
**Issue:**
- When progress is shown, the prefix might not include proper color reset
- ANSI codes could bleed into subsequent output if interrupted

#### D. Progress Display Suppressed Too Aggressively
**Location:** `import_task_done()` method
**Issue:**
- `quiet=False` is hardcoded in import path, but progress display logic still checks `quiet` flag
- This creates confusion about when output should appear

---

## 4. Test Scenarios

### Worker Stress Test
- Test with workers: 1, 2, 4, 8, 16, 32, 64, 128
- Monitor for: progress counter errors, duplicates, memory growth, thread pool saturation

### Sidecar Movement Test
- Create items with fetched LRC files
- Execute `beet move` with various album/item configurations
- Verify all .lrc files follow their parent files

### Import Output Test
- Import 5, 10, 20+ items
- Verify output is clear and progress is shown
- Check for proper formatting and color codes
