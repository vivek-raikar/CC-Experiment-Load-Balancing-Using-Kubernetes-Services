# Usage: .\test-load.ps1 -Requests 60 [-SleepMs 100] [-Url http://localhost:30080]
param(
    [int]$Requests = 60,
    [int]$SleepMs = 0,
    [string]$Url = "http://localhost:30080"
)
$pods = @()
$failed = 0
1..$Requests | ForEach-Object {
    $out = curl.exe -s --max-time 3 "$Url/api/whoami"
    try {
        $pods += ($out | ConvertFrom-Json -ErrorAction Stop).pod
    } catch {
        $failed++
    }
    if ($SleepMs -gt 0) { Start-Sleep -Milliseconds $SleepMs }
}
Write-Host "Total: $Requests   Success: $($pods.Count)   Failed: $failed"
$pods | Group-Object | Sort-Object Name |
    Select-Object @{n='Pod';e={$_.Name}}, @{n='Requests';e={$_.Count}},
                  @{n='Percent';e={[math]::Round($_.Count * 100 / $pods.Count, 1)}} |
    Format-Table -AutoSize
