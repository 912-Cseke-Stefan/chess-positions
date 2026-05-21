@echo OFF

python check_python_packets.py

if %errorlevel% NEQ 0 (
	echo:
	echo Python packages have to be installed
	echo:
	pause
	exit 1
)

echo Proceed...

python positions_labelling_fen_input.py --input selected_top_level_games.fen --output selected_top_level_games.csv --stockfish stockfish-windows-x86-64-bmi2.exe --workers 6 --depth 30