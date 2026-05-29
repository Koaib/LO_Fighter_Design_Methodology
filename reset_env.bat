@echo off
echo ================================
echo  LO Fighter Design Methodology
echo  Environment Reset
echo ================================
echo.
echo Deleting .venv...
rmdir /s /q .venv
echo.
echo Running setup...
python setup.py
echo.
pause