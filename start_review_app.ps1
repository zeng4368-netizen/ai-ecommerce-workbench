$log = "D:\codex\logs\streamlit_review.out.log"
$err = "D:\codex\logs\streamlit_review.err.log"
$p = Start-Process -FilePath "python" `
  -ArgumentList @("-m", "streamlit", "run", "src/ecom_ops/video_mixer/review_app.py", "--server.headless", "true", "--server.port", "8501") `
  -WorkingDirectory "D:\codex" `
  -RedirectStandardOutput $log `
  -RedirectStandardError $err `
  -PassThru -WindowStyle Hidden
Write-Output "streamlit pid=$($p.Id)"
