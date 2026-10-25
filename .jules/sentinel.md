## 2025-02-14 - Fix Command Injection in GitHub Actions
**Vulnerability:** Command injection vulnerability via `github.event.inputs` interpolation in `.github/workflows/execute_d1.yml`.
**Learning:** GitHub Actions expressions like `${{ github.event.inputs.sql_file }}` inside a `run` block create command injection risks because they are literally evaluated into the shell script before bash executes them. A malicious input string can terminate the command and execute arbitrary code.
**Prevention:** Always bind context expressions to environment variables (`env:`) and reference those environment variables within the bash script (e.g., `"$SQL_FILE"`).
