$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$thirdPartyRoot = Join-Path $projectRoot "third_party"
$tempRoot = Join-Path $projectRoot ".build-tools-temp"

$aria2Url = "https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip"
$ffmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"

function Download-Archive {
    param(
        [string]$Url,
        [string]$ZipPath
    )

    if (!(Test-Path $ZipPath)) {
        Write-Host "Downloading $Url"
        Invoke-WebRequest -Uri $Url -OutFile $ZipPath
    }
}

function Expand-ArchiveClean {
    param(
        [string]$ZipPath,
        [string]$Destination
    )

    if (Test-Path $Destination) {
        Remove-Item -Path $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Expand-Archive -Path $ZipPath -DestinationPath $Destination -Force
}

if (Test-Path $tempRoot) {
    Remove-Item -Path $tempRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
New-Item -ItemType Directory -Path $thirdPartyRoot -Force | Out-Null

$aria2Zip = Join-Path $tempRoot "aria2.zip"
$ffmpegZip = Join-Path $tempRoot "ffmpeg.zip"

Download-Archive -Url $aria2Url -ZipPath $aria2Zip
Download-Archive -Url $ffmpegUrl -ZipPath $ffmpegZip

$aria2Extract = Join-Path $tempRoot "aria2-extract"
$ffmpegExtract = Join-Path $tempRoot "ffmpeg-extract"

Expand-ArchiveClean -ZipPath $aria2Zip -Destination $aria2Extract
Expand-ArchiveClean -ZipPath $ffmpegZip -Destination $ffmpegExtract

$aria2Inner = Get-ChildItem -Path $aria2Extract -Directory | Select-Object -First 1
$ffmpegInner = Get-ChildItem -Path $ffmpegExtract -Directory | Select-Object -First 1

if (-not $aria2Inner) {
    throw "Unable to find aria2 extracted directory."
}
if (-not $ffmpegInner) {
    throw "Unable to find ffmpeg extracted directory."
}

$aria2Out = Join-Path $thirdPartyRoot "aria2"
$ffmpegOut = Join-Path $thirdPartyRoot "ffmpeg"

if (Test-Path $aria2Out) {
    Remove-Item -Path $aria2Out -Recurse -Force
}
if (Test-Path $ffmpegOut) {
    Remove-Item -Path $ffmpegOut -Recurse -Force
}

New-Item -ItemType Directory -Path $aria2Out -Force | Out-Null
New-Item -ItemType Directory -Path $ffmpegOut -Force | Out-Null

Copy-Item -Path (Join-Path $aria2Inner.FullName "*") -Destination $aria2Out -Recurse -Force
Copy-Item -Path (Join-Path $ffmpegInner.FullName "bin") -Destination (Join-Path $ffmpegOut "bin") -Recurse -Force

if (!(Test-Path (Join-Path $aria2Out "aria2c.exe"))) {
    throw "aria2c.exe was not copied successfully."
}
if (!(Test-Path (Join-Path $ffmpegOut "bin\ffmpeg.exe"))) {
    throw "ffmpeg.exe was not copied successfully."
}

Remove-Item -Path $tempRoot -Recurse -Force
Write-Host "Third-party binaries are ready in third_party/."
