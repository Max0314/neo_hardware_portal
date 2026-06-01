# 统一备份：MySQL dump + 四个命名卷（Windows PowerShell）
# 用法（在项目根目录）: .\scripts\backup-all.ps1
# 可选参数: .\scripts\backup-all.ps1 -BackupDir "D:\backups\hwstack_20260517"

param(
    [string]$BackupDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Get-ComposeProjectName {
    $envFile = Join-Path $Root ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*COMPOSE_PROJECT_NAME\s*=\s*(.+)\s*$') {
                return $Matches[1].Trim().Trim('"').Trim("'")
            }
        }
    }
    $vol = docker volume ls -q 2>$null | Where-Object { $_ -match '_mysql_data$' } | Select-Object -First 1
    if ($vol) {
        return $vol -replace '_mysql_data$', ''
    }
    return "hwstack"
}

function Read-DotEnvVar {
    param([string]$Name)
    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) { return $null }
    foreach ($line in Get-Content $envFile) {
        if ($line -match "^\s*$([regex]::Escape($Name))\s*=\s*(.+)\s*$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Prefix = Get-ComposeProjectName
if (-not $BackupDir) {
    $BackupDir = Join-Path $Root "backup\backup_$Stamp"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$Manifest = Join-Path $BackupDir "manifest.txt"
@(
    "backup_time=$Stamp"
    "compose_project=$Prefix"
    "backup_dir=$BackupDir"
) | Set-Content -Path $Manifest -Encoding UTF8

Write-Host "========== 统一备份 =========="
Write-Host "卷前缀: $Prefix"
Write-Host "输出目录: $BackupDir"

# MySQL dump
$mysqlRunning = docker compose ps mysql 2>$null | Select-String -Pattern "running|Up" -Quiet
if ($mysqlRunning) {
    $dumpFile = Join-Path $BackupDir "mysql_$Stamp.sql"
    Write-Host "导出 MySQL -> $dumpFile"
    docker compose exec -T mysql sh -c `
        'mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --single-transaction --routines --databases "$MYSQL_DATABASE"' `
        | Set-Content -Path $dumpFile -Encoding UTF8
    Add-Content $Manifest "mysql_dump=ok"
} else {
    Write-Warning "mysql 服务未运行，跳过 mysqldump"
    Add-Content $Manifest "mysql_dump=skipped"
}

$DataVolumes = @("mysql_data", "htmlsystm_data", "htmlsystm_uploads", "ai_chatroom_data")
$HelperImage = "alpine:3.19"

foreach ($vol in $DataVolumes) {
    $fq = "${Prefix}_${vol}"
    $out = Join-Path $BackupDir "$vol.tar.gz"
    $exists = docker volume inspect $fq 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "备份卷 $fq -> $out"
        docker pull $HelperImage 2>$null | Out-Null
        docker run --rm `
            -v "${fq}:/data:ro" `
            -v "${BackupDir}:/backup" `
            $HelperImage tar czf "/backup/$vol.tar.gz" -C /data .
        Add-Content $Manifest "$vol=ok"
    } else {
        Write-Warning "卷不存在，跳过: $fq"
        Add-Content $Manifest "$vol=missing"
    }
}

$envSrc = Join-Path $Root ".env"
if (Test-Path $envSrc) {
    Copy-Item $envSrc (Join-Path $BackupDir "env.snapshot")
    Add-Content $Manifest "env_snapshot=ok"
}

Write-Host ""
Write-Host "备份完成: $BackupDir"
Write-Host "清单: $Manifest"
Get-ChildItem $BackupDir -Filter "*.tar.gz" | ForEach-Object { Write-Host "  - $($_.Name)" }
