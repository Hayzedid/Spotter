@echo off
echo ========================================================
echo   Starting Spotter: Weather-Aware Truck Routing App
echo ========================================================
echo.

start "Spotter Django Backend" cmd /k "cd /d %~dp0backend && set DJANGO_DEBUG=True&& python manage.py runserver 8000"
start "Spotter React Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo Backend running at http://localhost:8000
echo Frontend running at http://localhost:3000
echo.
echo Both servers launched in separate windows!
