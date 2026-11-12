@echo off
chcp 65001 >nul
title Relance d'Ollama et telechargement de qwen2.5:7b
set "OLLAMA_MODELS=E:\ollama\models"
set "TEMP=E:\tmp"
set "TMP=E:\tmp"
echo Arret d'Ollama ...
taskkill /IM "ollama app.exe" /F >nul 2>&1
taskkill /IM "ollama.exe" /F >nul 2>&1
timeout /t 3 /nobreak >nul
echo Demarrage d'Ollama (modeles dans %OLLAMA_MODELS%) ...
start "" "E:\ollama\app\ollama app.exe"
timeout /t 10 /nobreak >nul
echo.
echo Telechargement de qwen2.5:7b (reprend la ou il s'est arrete) ...
"E:\ollama\app\ollama.exe" pull qwen2.5:7b
echo.
"E:\ollama\app\ollama.exe" list
echo.
echo Test rapide du modele :
"E:\ollama\app\ollama.exe" run qwen2.5:7b "Reponds juste: OK"
echo.
echo Termine.
pause
