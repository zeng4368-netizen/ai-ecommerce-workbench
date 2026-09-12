$ff = "C:\Program Files\Mozilla Firefox\firefox.exe"
& $ff --version 2>&1 | Select-Object -First 1
Start-Process -FilePath $ff -ArgumentList "https://www.tiktok.com/"
Write-Output "launched firefox to tiktok.com"
