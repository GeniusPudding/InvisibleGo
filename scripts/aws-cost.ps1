# Quick snapshot of what the InvisibleGo AWS deployment is costing.
# PowerShell twin of scripts/aws-cost.sh.
#
# Prints: running instances, Elastic IPs, EBS volumes, month-to-date
# cost by service, and next-month forecast. Region defaults to the
# same one the provision script uses (ap-northeast-1 / Tokyo).
#
# Requires: aws CLI configured (`aws configure`) and Cost Explorer
# enabled once in the Billing console (Cost Explorer API lives in
# us-east-1 regardless of resource region).

$ErrorActionPreference = 'Continue'

$Region   = if ($env:AWS_REGION) { $env:AWS_REGION } else { 'ap-northeast-1' }
$CeRegion = 'us-east-1'

$today        = (Get-Date).ToString('yyyy-MM-dd')
$monthStart   = (Get-Date -Day 1).ToString('yyyy-MM-dd')
# End date for get-cost-and-usage is exclusive; use tomorrow.
$monthEnd     = (Get-Date).AddDays(1).ToString('yyyy-MM-dd')
$forecastEnd  = (Get-Date).AddDays(30).ToString('yyyy-MM-dd')

Write-Host "=== Running EC2 instances in $Region ==="
aws ec2 describe-instances --region $Region `
    --filters "Name=instance-state-name,Values=pending,running,stopping,stopped" `
    --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name,PublicIpAddress,LaunchTime]' `
    --output table

Write-Host ""
Write-Host "=== Elastic IPs in $Region (attached EIP = free; detached = `$0.005/hr) ==="
aws ec2 describe-addresses --region $Region `
    --query 'Addresses[].[PublicIp,InstanceId,AllocationId,AssociationId]' `
    --output table

Write-Host ""
Write-Host "=== EBS volumes in $Region ==="
aws ec2 describe-volumes --region $Region `
    --query 'Volumes[].[VolumeId,Size,VolumeType,State,Attachments[0].InstanceId]' `
    --output table

Write-Host ""
Write-Host "=== Month-to-date cost by service ($monthStart -> $today) ==="
aws ce get-cost-and-usage --region $CeRegion `
    --time-period "Start=$monthStart,End=$monthEnd" `
    --granularity MONTHLY `
    --metrics UnblendedCost `
    --group-by Type=DIMENSION,Key=SERVICE `
    --query 'ResultsByTime[0].Groups[].[Keys[0],Metrics.UnblendedCost.Amount,Metrics.UnblendedCost.Unit]' `
    --output table
if (-not $?) {
    Write-Host "  (Cost Explorer not enabled? Open Billing -> Cost Explorer in the console once.)"
}

Write-Host ""
Write-Host "=== 30-day forecast ($today -> $forecastEnd) ==="
aws ce get-cost-forecast --region $CeRegion `
    --time-period "Start=$today,End=$forecastEnd" `
    --metric UNBLENDED_COST `
    --granularity MONTHLY `
    --query '[Total.Amount,Total.Unit]' `
    --output text
if (-not $?) {
    Write-Host "  (forecast needs ~7 days of data; try again later if empty)"
}
