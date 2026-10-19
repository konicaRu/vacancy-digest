# Регистрирует задачу в Планировщике Windows:
#   запуск через 3 минуты после входа в систему, только при наличии сети.
#   Повторный вход в тот же день письма не шлёт (это проверяет сам скрипт).
# Запуск: правый клик → «Выполнить с помощью PowerShell»
#   или: powershell -ExecutionPolicy Bypass -File register_task.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat  = Join-Path $root "run_digest.bat"
$taskName = "VacancyDigest"

$action   = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $root
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$trigger.Delay = "PT3M"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Утренний дайджест вакансий: Telegram, jabka.work, LinkedIn -> письмо" -Force | Out-Null

Write-Host "Задача '$taskName' зарегистрирована: запуск через 3 минуты после входа в Windows."
Write-Host "Проверить вручную: Start-ScheduledTask -TaskName $taskName"
