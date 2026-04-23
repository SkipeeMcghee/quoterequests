Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}
$env:FLASK_APP = 'run.py'
$env:FLASK_ENV = 'development'
Start-Process -FilePath "$PWD\.venv\Scripts\python.exe" -ArgumentList '-m flask run --host=127.0.0.1 --port=5000' -NoNewWindow
