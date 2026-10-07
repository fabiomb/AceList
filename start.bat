@echo off
rem Arranca AceList: ver start.ps1 para las opciones (-Port, -NoBrowser).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
