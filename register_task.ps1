# Регистрирует задачу в Планировщике Windows:
#   утренний выпуск — через 10 минут после входа в систему (успевает подключиться Browsec VPN), вечерний — ежедневно в 17:00 (время компьютера, МСК).
#   Каждый выпуск не чаще раза: повторный вход письма не шлёт (это проверяет сам скрипт).
#   Компьютер выключен в 17:00 — задача выполнится при включении (StartWhenAvailable).
# Запуск: правый клик → «Выполнить с помощью PowerShell»
#   или: powershell -ExecutionPolicy Bypass -File register_task.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat  = Join-Path $root "run_digest.bat"
$taskName = "VacancyDigest"

$action   = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $root
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = "PT10M"
$evening = New-ScheduledTaskTrigger -Daily -At "17:00"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($logon, $evening) -Settings $settings `
    -Description "Дайджест вакансий (утро и вечер): Telegram, jabka.work -> письмо" -Force | Out-Null

Write-Host "Задача '$taskName' зарегистрирована: через 10 минут после входа в Windows и ежедневно в 17:00."
Write-Host "Проверить вручную: Start-ScheduledTask -TaskName $taskName"
