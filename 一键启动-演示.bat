@echo off
cd /d "%~dp0"
echo Starting Data Analysis Agent Platform (Demo Mode)...
start "" pythonw launch_gui.pyw --silent --demo