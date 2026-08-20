# PowerShell启动脚本
Write-Host "========================================"
Write-Host "四六级汉译英短视频生成工具"
Write-Host "========================================"
Write-Host ""

Write-Host "正在检查虚拟环境..." -ForegroundColor Yellow
conda activate my_video

if ($LASTEXITCODE -ne 0) {
    Write-Host "错误: 无法激活 my_video 虚拟环境" -ForegroundColor Red
    Write-Host "请确保已创建该虚拟环境" -ForegroundColor Red
    pause
    exit 1
}

Write-Host "虚拟环境激活成功！" -ForegroundColor Green
Write-Host ""

Write-Host "正在启动Streamlit应用..." -ForegroundColor Yellow
streamlit run app.py

Read-Host "按回车键退出"
