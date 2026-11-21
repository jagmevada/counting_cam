# Starts the counter (no viewer window) and the recorder so that they keep running when this window, or
# Claude, is closed: they are created through WMI, outside the caller's process tree. On 2026-11-22 a
# restarted Claude session took both down with it, because they had been started from inside it.
#
#   powershell -File start.ps1             start whichever of the two is not running
#   powershell -File start.ps1 -Takeover   replace the running counter with the code on disk, no gap
#
# For the viewer window instead:  python counter.py --takeover   (that one stops when its terminal closes)
# Stop everything:
#   Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'counter\.py|recorder\.py|recordings' } | % { Stop-Process -Id $_.ProcessId -Force }
param([switch]$Takeover)

$py = (Get-Command python).Source
$jobs = @(
    @{ Script = 'counter.py'; Args = '--nogui'; Log = 'counter.log' },
    @{ Script = 'recorder.py'; Args = ''; Log = 'recorder.log' }
)
foreach ($job in $jobs) {
    $running = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -like "*$($job.Script)*" }
    $extra = $job.Args
    if ($running) {
        if (-not ($Takeover -and $job.Script -eq 'counter.py')) { "$($job.Script) is already running"; continue }
        $extra = "--takeover $extra"
    }
    $cmd = 'cmd.exe /c ""' + $py + '" -u ' + $job.Script + ' ' + $extra + ' >> ' + $job.Log + ' 2>&1"'
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $cmd; CurrentDirectory = $PSScriptRoot }
    if ($r.ReturnValue -eq 0) { "$($job.Script): started, pid $($r.ProcessId)" }
    else { "$($job.Script): could NOT start (code $($r.ReturnValue))" }
}
