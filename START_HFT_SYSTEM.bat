@echo off
title HFT System Launcher
color 0A

echo.
echo ========================================
echo     HFT SYSTEM LAUNCHER v2.0
echo ========================================
echo.

REM Change to the correct directory
cd /d "C:\Users\user\Desktop\HFT_sim"

REM Check if we're in the right directory
echo Checking directory structure...
if not exist "shared_utils.py" (
    echo.
    echo  ERROR: shared_utils.py not found!
    echo.
    echo Make sure these files are in C:\Users\user\Desktop\HFT_sim\:
    echo   - shared_utils.py
    echo   - exchange_server.py  
    echo   - relay_server.py
    echo   - shared_server.py
    echo   - trading_client.py
    echo   - network_config.json
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

if not exist "venv\Scripts\activate.bat" (
    echo.
    echo  ERROR: Virtual environment not found!
    echo.
    echo Please create a virtual environment first:
    echo   cd C:\Users\user\Desktop\HFT_sim
    echo   python -m venv venv
    echo   venv\Scripts\activate
    echo   pip install websockets rich colorama numpy pandas
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

echo  Directory structure looks good!
echo.

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate
if errorlevel 1 (
    echo  Failed to activate virtual environment
    pause
    exit /b 1
)

echo  Virtual environment activated!
echo.

REM Start servers with delays
echo  Starting Exchange Server...
start " Exchange Server" cmd /k "title Exchange Server && cd /d C:\Users\user\Desktop\HFT_sim && venv\Scripts\activate && python exchange_server.py"
echo    Wait 5 seconds for Exchange Server to start...
timeout /t 5 /nobreak >nul

echo  Starting Relay Server...
start " Relay Server" cmd /k "title Relay Server && cd /d C:\Users\user\Desktop\HFT_sim && venv\Scripts\activate && python relay_server.py"
echo    Wait 3 seconds for Relay Server to start...
timeout /t 3 /nobreak >nul

echo 🗄️ Starting Shared Data Server...
start " Shared Data Server" cmd /k "title Shared Data Server && cd /d C:\Users\user\Desktop\HFT_sim && venv\Scripts\activate && python shared_server.py"
echo    Wait 3 seconds for Shared Data Server to start...
timeout /t 3 /nobreak >nul

echo  Starting Trader 1...
start " Trader 1" cmd /k "title Trader 1 && cd /d C:\Users\user\Desktop\HFT_sim && venv\Scripts\activate && python trading_client.py --name TRADER1"
echo    Wait 2 seconds...
timeout /t 2 /nobreak >nul

echo  Starting Trader 2...
start "Trader 2" cmd /k "title Trader 2 && cd /d C:\Users\user\Desktop\HFT_sim && venv\Scripts\activate && python trading_client.py --name TRADER2"

echo.
echo ========================================
echo ✅ ALL COMPONENTS LAUNCHED!
echo ========================================
echo.
echo You should now see 5 windows:
echo   1.  Exchange Server
echo   2. Relay Server  
echo   3. 🗄️Shared Data Server
echo   4.  Trader 1
echo   5.  Trader 2
echo.
echo Check each window for "Ready" or "CONNECTED" messages
echo.
echo To stop all components: Close all windows or press Ctrl+C in each
echo.
pause
