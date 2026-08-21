# 自签证书生成（内测/开发用；正式上线请申请 CA 证书）
# 用法：PowerShell 管理员运行 .\deploy\gen-cert.ps1
$ErrorActionPreference = "Stop"

$certsDir = Join-Path $PSScriptRoot "certs"
New-Item -ItemType Directory -Force $certsDir | Out-Null

$cert = New-SelfSignedCertificate `
    -DnsName "172.28.252.38", "localhost" `
    -CertStoreLocation "cert:\LocalMachine\My" `
    -KeyAlgorithm RSA `
    -KeyLength 2048 `
    -NotAfter (Get-Date).AddYears(1)

$pwd = ConvertTo-SecureString -String "change-me" -Force -AsPlainText

# PKCS#12 → 拆分 nginx 所需 PEM
Export-PfxCertificate -Cert $cert -FilePath (Join-Path $certsDir "cert.pfx") -Password $pwd | Out-Null
$certPath = Join-Path $certsDir "cert.pem"
$keyPath  = Join-Path $certsDir "key.pem"

$certBytes = $cert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
[System.IO.File]::WriteAllBytes($certPath, $certBytes)
$rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)
$keyBytes = $rsa.ExportPkcs8PrivateKey()
[System.IO.File]::WriteAllBytes($keyPath, $keyBytes)

Write-Host "自签证书已生成："
Write-Host "  证书: $certPath"
Write-Host "  私钥: $keyPath（PKCS#8；nginx ssl_certificate_key 直接可用）"
Write-Host "有效期 1 年。正式上线请替换为 CA 证书。"
