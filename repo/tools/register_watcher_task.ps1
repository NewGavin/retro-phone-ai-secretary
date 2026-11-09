# Register (or update) the OldPhoneWatcher scheduled task.
# Runs at user logon with an INTERACTIVE token, i.e. in the user's normal
# session (medium integrity) - this is required because DSH's Windows sandbox
# cannot initialize without a real login session, and because the watcher must
# be able to spawn the dsh CLI with the user's own environment.
# ASCII only: PowerShell 5.1 reads BOM-less files as ANSI.
$ErrorActionPreference = "Stop"
$taskName = "OldPhoneWatcher"
$container = "F:/projects/oldphone-ata"
$root = "F:/projects/oldphone-ata/repo"

$svc = New-Object -ComObject Schedule.Service
$svc.Connect()
$folder = $svc.GetFolder("\")
try { $folder.DeleteTask($taskName, 0) } catch { }

$td = $svc.NewTask(0)
$td.RegistrationInfo.Description = "oldphone-ata: watch recordings and run ASR/agent/callback"
$td.Settings.Enabled = $true
$td.Settings.DisallowStartIfOnBatteries = $false
$td.Settings.StopIfGoingOnBatteries = $false
$td.Settings.ExecutionTimeLimit = "PT0S"
$td.Settings.StartWhenAvailable = $true
$td.Settings.RestartCount = 2
$td.Settings.RestartInterval = "PT1M"
$td.Principal.LogonType = 3   # TASK_LOGON_INTERACTIVE_TOKEN
$td.Principal.RunLevel = 0    # TASK_RUNLEVEL_LUA (no elevation)

$trig = $td.Triggers.Create(9)  # TASK_TRIGGER_LOGON
$trig.UserId = "$env:USERDOMAIN" + "\" + "$env:USERNAME"

$act = $td.Actions.Create(0)    # TASK_ACTION_EXEC
$act.Path = Join-Path $container ".venv/Scripts/pythonw.exe"
$act.Arguments = '"' + (Join-Path $root "tools/watch_recordings.py") + '"'
$act.WorkingDirectory = $root

$folder.RegisterTaskDefinition($taskName, $td, 6, $null, $null, 3) | Out-Null
Write-Output "registered: $taskName"
$t = $folder.GetTask($taskName)
$t.Run($null) | Out-Null
Write-Output "started: $taskName"
