# Auto-activate Detectron conda environment
# This will automatically activate when Cursor opens a new terminal
# Environment path: C:\Users\BenSc\anaconda3\envs\Detectron
Start-Sleep -Milliseconds 100
if (Get-Command conda -ErrorAction SilentlyContinue) {
    conda activate Detectron | Out-Null
    Write-Host "Activated conda environment: Detectron" -ForegroundColor Green
    Write-Host "  Python:" (python --version 2>&1) -ForegroundColor Gray
    Write-Host "  Path: C:\Users\BenSc\anaconda3\envs\Detectron" -ForegroundColor Gray
}
