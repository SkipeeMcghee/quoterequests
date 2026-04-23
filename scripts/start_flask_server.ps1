$ErrorActionPreference = 'Stop'
$env:FLASK_APP = 'run.py'
$env:FLASK_ENV = 'development'
$env:SECRET_KEY = 'dev-secret-key'
Set-Location 'C:\xampp\htdocs\quoterequests'
$p = Start-Process -FilePath 'C:\xampp\htdocs\quoterequests\.venv\Scripts\python.exe' -ArgumentList '-m', 'flask', 'run' -WorkingDirectory 'C:\xampp\htdocs\quoterequests' -WindowStyle Hidden -RedirectStandardOutput 'C:\xampp\htdocs\quoterequests\server.log' -RedirectStandardError 'C:\xampp\htdocs\quoterequests\server.err' -PassThru
Write-Output $p.Id
