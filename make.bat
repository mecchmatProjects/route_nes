@echo off
setlocal
set PYTHON=.venv\Scripts\python.exe

if "%1"=="" goto test
if "%1"=="test" goto test
if "%1"=="test-load" goto test-load
if "%1"=="test-exclude" goto test-exclude
if "%1"=="test-special" goto test-special
if "%1"=="test-phase1" goto test-phase1
if "%1"=="test-phase2" goto test-phase2
if "%1"=="venv" goto venv
if "%1"=="clean" goto clean
if "%1"=="help" goto help

echo Unknown target: %1
goto help

:venv
py -3 -m venv .venv
%PYTHON% -m pip install --upgrade pip
goto end

:test
call :test-load
if errorlevel 1 goto fail
call :test-exclude
if errorlevel 1 goto fail
call :test-special
if errorlevel 1 goto fail
call :test-phase1
if errorlevel 1 goto fail
call :test-phase2
if errorlevel 1 goto fail
echo.
echo ============================================================
echo   ALL TEST SUITES PASSED
echo ============================================================
goto end

:test-load
echo --- test_load_validate ---
%PYTHON% test_load_validate.py
exit /b %errorlevel%

:test-exclude
echo --- test_exclude_exceptions ---
%PYTHON% test_exclude_exceptions.py
exit /b %errorlevel%

:test-special
echo --- test_special_routes ---
%PYTHON% test_special_routes.py
exit /b %errorlevel%

:test-phase1
echo --- test_phase1 ---
%PYTHON% test_phase1.py
exit /b %errorlevel%

:test-phase2
echo --- test_phase2 ---
%PYTHON% test_phase2.py
exit /b %errorlevel%

:clean
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
del /s /q *.pyc >nul 2>&1
echo Cleaned.
goto end

:help
echo Usage: make [target]
echo.
echo Targets:
echo   test          Run all test suites (default)
echo   test-load     Run load ^& validate tests
echo   test-exclude  Run exclusion ^& exceptions tests
echo   test-special  Run special routes tests
echo   test-phase1   Run Phase 1 score ^& schedule tests
echo   test-phase2   Run Phase 2 routing tests
echo   venv          Create virtual environment
echo   clean         Remove __pycache__ and .pyc files
echo   help          Show this message
goto end

:fail
echo.
echo TESTS FAILED
exit /b 1

:end
endlocal
