@echo off

echo Uploading progress to GitHub...

set /p RESULT=<progress.txt

git add . && git commit -m "Positions: %RESULT%" && git push

pause