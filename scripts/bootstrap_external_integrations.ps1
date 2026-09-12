param(
    [switch]$Refresh
)

$ErrorActionPreference = "Stop"
$WorkspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ExternalRoot = [System.IO.Path]::GetFullPath((Join-Path $WorkspaceRoot "external"))

function Invoke-GitChecked {
    param([string[]]$GitArguments)
    & git -c http.version=HTTP/1.1 @GitArguments
    if ($LASTEXITCODE -ne 0) {
        throw "git failed with exit code ${LASTEXITCODE}: git $($GitArguments -join ' ')"
    }
}

function Install-CommitArchive {
    param(
        [hashtable]$Integration,
        [string]$Target
    )
    $DownloadRoot = Join-Path $ExternalRoot (".download-" + $Integration.Directory)
    $ArchivePath = Join-Path $DownloadRoot "source.zip"
    $ExtractPath = Join-Path $DownloadRoot "extract"
    $ArchiveUrl = "https://codeload.github.com/$($Integration.OwnerRepo)/zip/$($Integration.Commit)"
    if (-not (Test-Path -LiteralPath $DownloadRoot)) {
        New-Item -ItemType Directory -Path $DownloadRoot | Out-Null
    }
    if (Test-Path -LiteralPath $ExtractPath) {
        Remove-Item -LiteralPath $ExtractPath -Recurse -Force
    }
    try {
        $HasReusableArchive = (
            (Test-Path -LiteralPath $ArchivePath) -and
            (Get-Item -LiteralPath $ArchivePath).Length -gt 0
        )
        if (-not $HasReusableArchive) {
            if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
                & curl.exe --fail --location --retry 3 --retry-delay 2 --output $ArchivePath $ArchiveUrl
                if ($LASTEXITCODE -ne 0) {
                    throw "$($Integration.Name): curl download failed with exit code $LASTEXITCODE."
                }
            } else {
                Invoke-WebRequest -UseBasicParsing -TimeoutSec 180 -Uri $ArchiveUrl -OutFile $ArchivePath
            }
        } else {
            Write-Output "$($Integration.Name): reusing previously downloaded commit archive."
        }
        New-Item -ItemType Directory -Path $ExtractPath | Out-Null
        if (Get-Command tar.exe -ErrorAction SilentlyContinue) {
            & tar.exe -xf $ArchivePath -C $ExtractPath
            if ($LASTEXITCODE -ne 0) {
                throw "$($Integration.Name): archive extraction failed with exit code $LASTEXITCODE."
            }
        } else {
            Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ExtractPath
        }
        $SourceDirectory = Get-ChildItem -LiteralPath $ExtractPath -Directory | Select-Object -First 1
        if ($null -eq $SourceDirectory) {
            throw "$($Integration.Name): archive contained no source directory."
        }
        Move-Item -LiteralPath $SourceDirectory.FullName -Destination $Target
        @{
            repository = $Integration.Repository
            commit = $Integration.Commit
            method = "github-commit-archive"
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Target ".integration-source.json") -Encoding utf8
    } finally {
        if (Test-Path -LiteralPath $DownloadRoot) {
            Remove-Item -LiteralPath $DownloadRoot -Recurse -Force
        }
    }
}

if (-not (Test-Path -LiteralPath $ExternalRoot)) {
    New-Item -ItemType Directory -Path $ExternalRoot | Out-Null
}

$Integrations = @(
    @{
        Name = "Postiz"
        OwnerRepo = "gitroomhq/postiz-app"
        Repository = "https://github.com/gitroomhq/postiz-app.git"
        Commit = "60329af4a0781d8067bbcfdf3631011f6d159be7"
        Directory = "postiz-app"
    },
    @{
        Name = "BrightBean Studio"
        OwnerRepo = "brightbeanxyz/brightbean-studio"
        Repository = "https://github.com/brightbeanxyz/brightbean-studio.git"
        Commit = "e4da3a2c2b717f9140af54a7a03a34b90ae4cf59"
        Directory = "brightbean-studio"
    },
    @{
        Name = "Multica"
        OwnerRepo = "multica-ai/multica"
        Repository = "https://github.com/multica-ai/multica.git"
        Commit = "6b56bc05a4a5e3e189ff1da9ce31bdf465ac5528"
        Directory = "multica"
    }
)

$Failures = @()
foreach ($Integration in $Integrations) {
    $Target = [System.IO.Path]::GetFullPath((Join-Path $ExternalRoot $Integration.Directory))
    $ExpectedPrefix = $ExternalRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $Target.StartsWith($ExpectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside external directory: $Target"
    }
    try {
        if (Test-Path -LiteralPath $Target) {
            $HasGit = Test-Path -LiteralPath (Join-Path $Target ".git")
            $HasArchiveMarker = Test-Path -LiteralPath (Join-Path $Target ".integration-source.json")
            $IsManaged = $HasGit -or $HasArchiveMarker
            if (-not $IsManaged) {
                throw "Target exists but is not a managed integration: $Target"
            }
            $GitCommitMatches = $false
            if ($HasGit) {
                try {
                    $ExistingCommit = & git -C $Target rev-parse HEAD 2>$null
                    $GitCommitMatches = (
                        $LASTEXITCODE -eq 0 -and
                        $null -ne $ExistingCommit -and
                        "$ExistingCommit".Trim() -eq $Integration.Commit
                    )
                } catch {
                    $GitCommitMatches = $false
                }
            }
            $HasWorktree = Test-Path -LiteralPath (Join-Path $Target "README.md")
            if (-not $Refresh -and $HasWorktree -and ($HasArchiveMarker -or $GitCommitMatches)) {
                Write-Output "$($Integration.Name): already present, skipped."
                continue
            }
            Remove-Item -LiteralPath $Target -Recurse -Force
        }

        $CachedArchive = Join-Path (Join-Path $ExternalRoot (".download-" + $Integration.Directory)) "source.zip"
        if ((Test-Path -LiteralPath $CachedArchive) -and (Get-Item -LiteralPath $CachedArchive).Length -gt 0) {
            Install-CommitArchive -Integration $Integration -Target $Target
            Write-Output "$($Integration.Name): ready from cached commit archive $($Integration.Commit)"
            continue
        }

        $Cloned = $false
        for ($Attempt = 1; $Attempt -le 2; $Attempt++) {
            try {
                Invoke-GitChecked -GitArguments @(
                    "clone", "--filter=blob:none", "--no-checkout",
                    $Integration.Repository, $Target
                )
                $Cloned = $true
                break
            } catch {
                if (Test-Path -LiteralPath $Target) {
                    Remove-Item -LiteralPath $Target -Recurse -Force
                }
                Write-Output "$($Integration.Name): Git attempt $Attempt failed."
            }
        }

        if ($Cloned) {
            try {
                Invoke-GitChecked -GitArguments @(
                    "-C", $Target, "fetch", "--depth", "1", "origin", $Integration.Commit
                )
                Invoke-GitChecked -GitArguments @(
                    "-C", $Target, "checkout", "--detach", $Integration.Commit
                )
                $ActualCommit = & git -C $Target rev-parse HEAD
                if ($LASTEXITCODE -ne 0 -or $ActualCommit.Trim() -ne $Integration.Commit) {
                    throw "$($Integration.Name): checked-out commit could not be verified."
                }
                Write-Output "$($Integration.Name): ready from Git at $ActualCommit"
            } catch {
                Write-Output "$($Integration.Name): Git checkout failed, using commit archive fallback."
                if (Test-Path -LiteralPath $Target) {
                    Remove-Item -LiteralPath $Target -Recurse -Force
                }
                Install-CommitArchive -Integration $Integration -Target $Target
                Write-Output "$($Integration.Name): ready from commit archive $($Integration.Commit)"
            }
        } else {
            Write-Output "$($Integration.Name): using commit archive fallback."
            Install-CommitArchive -Integration $Integration -Target $Target
            Write-Output "$($Integration.Name): ready from commit archive $($Integration.Commit)"
        }
    } catch {
        $Failures += "$($Integration.Name): $($_.Exception.Message)"
        Write-Warning $Failures[-1]
    }
}

if ($Failures.Count -gt 0) {
    Write-Output "Integration bootstrap completed with failures:"
    $Failures | ForEach-Object { Write-Output "- $_" }
    exit 1
}
