@echo off
echo 🚀 Railway Deploy Script
echo ========================

echo.
echo Проверяем статус...
python check_railway_status.py

echo.
echo Запускаем деплой...
python railway_deploy.py

echo.
echo Готово! Проверьте Railway Dashboard для статуса деплоя.
pause
