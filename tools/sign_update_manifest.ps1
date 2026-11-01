param(
    [Parameter(Mandatory=$true)][string]$InputPath,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [Parameter(Mandatory=$true)][string]$KeyPath,
    [Parameter(Mandatory=$true)][string]$PublicKeyOutput,
    [ValidatePattern('^[A-Za-z0-9_-]{1,80}$')][string]$KeyId='pb-update-20261101',
    [switch]$InitializeKey
)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Security
$taskUtf8=New-Object System.Text.UTF8Encoding($false,$true)
$taskInput=(Resolve-Path -LiteralPath $InputPath).Path
$taskOutput=[IO.Path]::GetFullPath($OutputPath)
$taskKey=[IO.Path]::GetFullPath($KeyPath)
$taskPublic=[IO.Path]::GetFullPath($PublicKeyOutput)
$taskBytes=[IO.File]::ReadAllBytes($taskInput)
if($taskBytes.Length -gt 32768){throw 'Canonical payload exceeds the permitted length.'}
if($taskBytes.Length -ge 3 -and $taskBytes[0] -eq 239 -and $taskBytes[1] -eq 187 -and $taskBytes[2] -eq 191){throw 'Canonical UTF-8 payload must not contain a BOM.'}
$taskPayload=$taskUtf8.GetString($taskBytes) | ConvertFrom-Json
$taskRsa=New-Object Security.Cryptography.RSACryptoServiceProvider(2048)
$taskRsa.PersistKeyInCsp=$false
try {
    if(Test-Path -LiteralPath $taskKey){
        $taskProtected=[IO.File]::ReadAllBytes($taskKey)
        $taskPrivate=[Security.Cryptography.ProtectedData]::Unprotect($taskProtected,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
        try {$taskRsa.FromXmlString($taskUtf8.GetString($taskPrivate))}
        finally {[Array]::Clear($taskPrivate,0,$taskPrivate.Length)}
    } else {
        if(-not $InitializeKey){throw 'Signing key does not exist; initialize explicitly once.'}
        $taskPrivate=$taskUtf8.GetBytes($taskRsa.ToXmlString($true))
        try {$taskProtected=[Security.Cryptography.ProtectedData]::Protect($taskPrivate,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)}
        finally {[Array]::Clear($taskPrivate,0,$taskPrivate.Length)}
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($taskKey)) | Out-Null
        [IO.File]::WriteAllBytes($taskKey,$taskProtected)
    }
    if($taskRsa.KeySize -ne 2048){throw 'Only the pinned RSA-2048 signing format is supported.'}
    $taskParameters=$taskRsa.ExportParameters($false)
    $taskExponent=0
    foreach($taskByte in $taskParameters.Exponent){$taskExponent=$taskExponent*256+[int]$taskByte}
    if($taskExponent -ne 65537){throw 'Unexpected public exponent.'}
    $taskPublicInfo=[ordered]@{key_id=$KeyId;modulus_b64=[Convert]::ToBase64String($taskParameters.Modulus);exponent=$taskExponent}
    $taskSignature=$taskRsa.SignData($taskBytes,[Security.Cryptography.HashAlgorithmName]::SHA256,[Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $taskEnvelope=[ordered]@{algorithm='rsa-pkcs1-sha256';key_id=$KeyId;payload=$taskPayload;signature=[Convert]::ToBase64String($taskSignature)}
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($taskOutput)) | Out-Null
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($taskPublic)) | Out-Null
    [IO.File]::WriteAllText($taskOutput,($taskEnvelope | ConvertTo-Json -Depth 12 -Compress),$taskUtf8)
    [IO.File]::WriteAllText($taskPublic,($taskPublicInfo | ConvertTo-Json -Depth 4 -Compress),$taskUtf8)
    Write-Output "Signed update metadata with public key id $KeyId."
} finally {
    $taskRsa.Dispose()
    if($taskProtected){[Array]::Clear($taskProtected,0,$taskProtected.Length)}
}
