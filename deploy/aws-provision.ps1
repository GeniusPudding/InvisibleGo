# Provision InvisibleGo's VM on AWS EC2 from Windows PowerShell.
#
# Prerequisites:
#   - AWS CLI installed and `aws configure` already run
#   - PowerShell 5.1 (built-in) or 7+
#
# Run (from repo root):
#   powershell -ExecutionPolicy Bypass -File .\deploy\aws-provision.ps1
#
# Idempotent: detects existing key pair / security group / instance /
# Elastic IP by name and skips creation, so it's safe to re-run.

# Use manual $LASTEXITCODE checks instead of ErrorActionPreference=Stop.
# PowerShell 7.3+ turns native-command stderr into a terminating exception
# when Stop is active, which the aws CLI triggers for benign "resource not
# found" responses we want to detect and branch on.
$ErrorActionPreference = 'Continue'
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$Region       = 'ap-northeast-1'
$KeyName      = 'InvisibleGoKey'
$SgName       = 'invisiblego-sg'
$InstanceName = 'invisiblego'
$InstanceType = 't3.micro'
$KeyFile      = Join-Path $HOME "$KeyName.pem"

function Run-Aws {
    # Wrapper that lets us detect non-zero exit codes from native `aws`.
    $output = & aws @args 2>&1
    return @{ Output = $output; ExitCode = $LASTEXITCODE }
}

Write-Host '==> Checking AWS credentials'
$arn = aws sts get-caller-identity --query 'Arn' --output text
if ($LASTEXITCODE -ne 0) {
    Write-Host '!! aws sts get-caller-identity failed. Did you run `aws configure`?'
    exit 1
}
Write-Host "   $arn"

# --- Key pair -------------------------------------------------------
aws ec2 describe-key-pairs --key-names $KeyName --region $Region 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "==> Key pair '$KeyName' already exists in AWS"
    if (-not (Test-Path $KeyFile)) {
        Write-Host "!! $KeyFile is missing locally and AWS cannot regenerate the private key."
        Write-Host '   Delete the key pair in AWS and re-run:'
        Write-Host "     aws ec2 delete-key-pair --key-name $KeyName --region $Region"
        exit 1
    }
} else {
    Write-Host "==> Creating key pair '$KeyName'"
    $keyMaterial = aws ec2 create-key-pair --key-name $KeyName `
        --query 'KeyMaterial' --output text --region $Region
    if ($LASTEXITCODE -ne 0) { exit 1 }
    Set-Content -Path $KeyFile -Value $keyMaterial -Encoding ASCII
    # Lock permissions so OpenSSH stops warning about the key being world-readable
    icacls $KeyFile /inheritance:r | Out-Null
    icacls $KeyFile /grant:r "$($env:USERNAME):(R)" | Out-Null
    Write-Host "   Saved to $KeyFile"
}

# --- Security group -------------------------------------------------
$MyIP = (Invoke-RestMethod 'https://checkip.amazonaws.com').Trim()
Write-Host "==> Your public IP: $MyIP"

$SgId = aws ec2 describe-security-groups --group-names $SgName --region $Region `
    --query 'SecurityGroups[0].GroupId' --output text 2>$null
if ($LASTEXITCODE -eq 0 -and $SgId -and $SgId -ne 'None') {
    Write-Host "==> Security group '$SgName' already exists ($SgId)"
} else {
    Write-Host "==> Creating security group '$SgName'"
    $SgId = aws ec2 create-security-group --group-name $SgName `
        --description 'InvisibleGo web server' --region $Region `
        --query 'GroupId' --output text
    if ($LASTEXITCODE -ne 0) { exit 1 }
    aws ec2 authorize-security-group-ingress --group-id $SgId --protocol tcp --port 22  --cidr "$MyIP/32" --region $Region | Out-Null
    aws ec2 authorize-security-group-ingress --group-id $SgId --protocol tcp --port 80  --cidr '0.0.0.0/0' --region $Region | Out-Null
    aws ec2 authorize-security-group-ingress --group-id $SgId --protocol tcp --port 443 --cidr '0.0.0.0/0' --region $Region | Out-Null
    Write-Host "   Opened: 22 from $MyIP, 80 and 443 public"
}

# --- Latest Ubuntu 24.04 AMI ----------------------------------------
Write-Host "==> Resolving latest Ubuntu 24.04 AMI in $Region"
$AmiId = aws ec2 describe-images `
    --owners 099720109477 `
    --filters 'Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*' 'Name=state,Values=available' `
    --query 'sort_by(Images, &CreationDate)[-1].ImageId' `
    --output text `
    --region $Region
if ($LASTEXITCODE -ne 0 -or -not $AmiId -or $AmiId -eq 'None') { Write-Host '!! Could not resolve AMI'; exit 1 }
Write-Host "   AMI: $AmiId"

# --- Instance -------------------------------------------------------
$InstanceId = aws ec2 describe-instances `
    --filters "Name=tag:Name,Values=$InstanceName" 'Name=instance-state-name,Values=pending,running,stopped,stopping' `
    --query 'Reservations[].Instances[0].InstanceId' `
    --output text `
    --region $Region 2>$null

if ($InstanceId -and $InstanceId -ne 'None') {
    Write-Host "==> Instance '$InstanceName' already exists ($InstanceId)"
} else {
    Write-Host "==> Launching $InstanceType Ubuntu 24.04 instance"
    $InstanceId = aws ec2 run-instances `
        --image-id $AmiId `
        --count 1 `
        --instance-type $InstanceType `
        --key-name $KeyName `
        --security-group-ids $SgId `
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$InstanceName}]" `
        --region $Region `
        --query 'Instances[0].InstanceId' `
        --output text
    if ($LASTEXITCODE -ne 0) { exit 1 }
    Write-Host "   Launched: $InstanceId"
    Write-Host '   Waiting for instance to reach running state (30-60 seconds)...'
    aws ec2 wait instance-running --instance-ids $InstanceId --region $Region
}

# --- Elastic IP -----------------------------------------------------
$Eip = aws ec2 describe-addresses `
    --filters "Name=instance-id,Values=$InstanceId" `
    --query 'Addresses[0].PublicIp' `
    --output text `
    --region $Region 2>$null

if ($Eip -and $Eip -ne 'None') {
    $PublicIp = $Eip
    Write-Host "==> Elastic IP already attached: $PublicIp"
} else {
    Write-Host '==> Allocating and associating Elastic IP'
    $AllocId = aws ec2 allocate-address --domain vpc --region $Region `
        --query 'AllocationId' --output text
    aws ec2 associate-address --instance-id $InstanceId --allocation-id $AllocId --region $Region | Out-Null
    $PublicIp = aws ec2 describe-addresses --allocation-ids $AllocId `
        --query 'Addresses[0].PublicIp' --output text --region $Region
    Write-Host "   IP: $PublicIp"
}

Write-Host ''
Write-Host '====================================================================='
Write-Host ' Provisioning complete.'
Write-Host '====================================================================='
Write-Host ''
Write-Host " Instance:   $InstanceId  ($InstanceType, Ubuntu 24.04, $Region)"
Write-Host " Public IP:  $PublicIp"
Write-Host " SSH key:    $KeyFile"
Write-Host ''
Write-Host ' Next - SSH in and install the app:'
Write-Host ''
Write-Host "   ssh -i $KeyFile ubuntu@$PublicIp"
Write-Host '   # inside the VM:'
Write-Host '   git clone https://github.com/GeniusPudding/InvisibleGo.git'
Write-Host '   cd InvisibleGo'
Write-Host '   sudo bash deploy/setup.sh'
Write-Host ''
Write-Host ' Tear down later to stop billing:'
Write-Host "   aws ec2 terminate-instances --instance-ids $InstanceId --region $Region"
Write-Host '   (also release the Elastic IP, see README)'
Write-Host ''
