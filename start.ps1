Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Starting Spotter: Weather-Aware Truck Routing App" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend'; `$env:DJANGO_DEBUG='True'; python manage.py runserver 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\frontend'; npm run dev"

Write-Host "`nBackend: http://localhost:8000" -ForegroundColor Yellow
Write-Host "Frontend: http://localhost:3000" -ForegroundColor Yellow
Write-Host "`nBoth services launched in separate windows!" -ForegroundColor Green
