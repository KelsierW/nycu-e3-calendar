param([string]$TaskName = 'NYCU e3 Coursework Check')
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Create .venv and install this project first.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'config.yaml'))) { throw 'config.yaml is missing.' }
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and (($existing.Actions.Arguments -join ' ') -notlike ('*' + $projectRoot + '*'))) {
    throw 'A different task already uses this name; no changes made.'
}
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
function EscapeXml([string]$value) { [Security.SecurityElement]::Escape($value) }
$taipeiDate = [DateTimeOffset]::UtcNow.ToOffset([TimeSpan]::FromHours(8)).ToString('yyyy-MM-dd')
$triggers = foreach ($hour in @('08','12','16','20')) {
    '<CalendarTrigger><StartBoundary>' + $taipeiDate + 'T' + $hour + ':00:00+08:00</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>'
}
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<RegistrationInfo><Description>NYCU e3 local Python; Asia/Taipei 08:00,12:00,16:00,20:00. Logs: LOCALAPPDATA/NYCU-e3-calendar/out. Requires signed-in user and Google OAuth.</Description></RegistrationInfo>
<Triggers>$($triggers -join '')</Triggers>
<Principals><Principal id="Author"><UserId>$(EscapeXml $user)</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>true</Hidden><WakeToRun>true</WakeToRun><ExecutionTimeLimit>PT30M</ExecutionTimeLimit><RestartOnFailure><Interval>PT15M</Interval><Count>2</Count></RestartOnFailure></Settings>
<Actions Context="Author"><Exec><Command>$(EscapeXml $python)</Command><Arguments>$(EscapeXml ('-u "' + (Join-Path $projectRoot 'scripts\run_windows_check.py') + '"'))</Arguments><WorkingDirectory>$(EscapeXml $projectRoot)</WorkingDirectory></Exec></Actions>
</Task>
"@
Register-ScheduledTask -TaskName $TaskName -Xml $xml -Force | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object LastRunTime,LastTaskResult,NextRunTime
$pythonConsole = Join-Path $projectRoot '.venv\Scripts\python.exe'
$digestEnabled = (& $pythonConsole -c "import sys,yaml; print('true' if yaml.safe_load(open(sys.argv[1],encoding='utf-8-sig')).get('daily_digest',False) else 'false')" (Join-Path $projectRoot 'config.yaml')) -eq 'true'
$digestTaskName = $TaskName + ' - Morning Digest Prep'
$existingDigest = Get-ScheduledTask -TaskName $digestTaskName -ErrorAction SilentlyContinue
if ($existingDigest -and (($existingDigest.Actions.Arguments -join ' ') -notlike ('*' + $projectRoot + '*'))) {
    throw 'A different task already uses the morning digest name; no changes made to it.'
}
if ($digestEnabled) {
    $digestTrigger = '<Triggers><CalendarTrigger><StartBoundary>' + $taipeiDate + 'T07:45:00+08:00</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>'
    $digestXml = [regex]::Replace($xml, '(?s)<Triggers>.*?</Triggers>', $digestTrigger)
    $digestXml = $digestXml.Replace('Asia/Taipei 08:00,12:00,16:00,20:00.', 'Asia/Taipei 07:45 preparation for the 08:00 Google Calendar mobile digest.')
    Register-ScheduledTask -TaskName $digestTaskName -Xml $digestXml -Force | Select-Object TaskName,State
    Get-ScheduledTaskInfo -TaskName $digestTaskName | Select-Object LastRunTime,LastTaskResult,NextRunTime
} elseif ($existingDigest) {
    Disable-ScheduledTask -TaskName $digestTaskName | Out-Null
}
