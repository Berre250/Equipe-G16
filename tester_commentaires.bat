@echo off
chcp 65001 >nul
title Test du classement des commentaires (exemples)
cd /d "%~dp0"
rem Les resultats du test vont dans resultats_demo\ pour ne pas melanger avec les vraies donnees
set "TRENDS_DIR=%~dp0resultats_demo"
set "PYTHONIOENCODING=utf-8"
python comment_analyzer.py --in-dir exemples
echo.
pause
