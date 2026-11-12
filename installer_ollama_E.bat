@echo off
chcp 65001 >nul
title Installation d'Ollama sur E:
cd /d "%~dp0"
echo ============================================================
echo   Installation d'Ollama et de qwen2.5:7b sur le disque E:
echo ============================================================
echo.
set "SETUP=%USERPROFILE%\Downloads\OllamaSetup.exe"
if not exist "%SETUP%" (
  echo [ERREUR] %SETUP% introuvable.
  goto fin
)
for /f %%G in ('powershell -NoProfile -Command "[math]::Floor((Get-PSDrive E).Free/1GB)"') do set FREE_E=%%G
echo Espace libre sur E: : %FREE_E% Go
if %FREE_E% LSS 10 (
  echo [ERREUR] Il faut au moins 10 Go libres sur E:. Rien n'a ete installe.
  goto fin
)

rem C: est plein : tous les fichiers temporaires vont sur E:
if not exist "E:\tmp" mkdir "E:\tmp"
set "TEMP=E:\tmp"
set "TMP=E:\tmp"
set "OLLAMA_MODELS=E:\ollama\models"
setx OLLAMA_MODELS "E:\ollama\models" >nul

echo [1/3] Installation d'Ollama dans E:\ollama\app (1 a 3 minutes) ...
"%SETUP%" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="E:\ollama\app"
if errorlevel 1 (
  echo [ERREUR] L'installation a echoue (code %errorlevel%).
  goto fin
)
set "PATH=E:\ollama\app;%PATH%"

echo [2/3] Demarrage d'Ollama ...
taskkill /IM "ollama app.exe" /F >nul 2>&1
taskkill /IM "ollama.exe" /F >nul 2>&1
if exist "E:\ollama\app\ollama app.exe" (
  start "" "E:\ollama\app\ollama app.exe"
) else (
  start "" /min "E:\ollama\app\ollama.exe" serve
)
timeout /t 10 /nobreak >nul
ollama --version

echo [3/3] Telechargement de qwen2.5:7b dans E:\ollama\models (environ 5 Go) ...
ollama pull qwen2.5:7b
if errorlevel 1 echo [ATTENTION] Telechargement interrompu : relance ce script, il reprendra ou il s'est arrete.

echo.
echo ============================================================
echo   Verification
echo ============================================================
where ollama
ollama list
echo Modeles stockes dans : %OLLAMA_MODELS%

:fin
echo.
echo Termine. Ferme cette fenetre, puis ferme et rouvre VS Code (pour qu'il voie Ollama).
pause
