-- Read-only schema audit for JEE PYQ Master.
-- This file intentionally performs SELECT only; it does not alter production data.
SELECT name, type, sql
FROM sqlite_master
WHERE type IN ('table', 'view', 'index')
  AND name NOT LIKE 'sqlite_%'
ORDER BY type, name;
