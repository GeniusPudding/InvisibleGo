#!/usr/bin/env bash
# Quick snapshot of what the InvisibleGo AWS deployment is costing.
#
# Prints: running instances, Elastic IPs, EBS volumes, month-to-date
# cost by service, and next-month forecast. Region defaults to the
# same one the provision script uses (ap-northeast-1 / Tokyo).
#
# Requires: aws CLI configured (`aws configure`) and Cost Explorer
# enabled once in the Billing console (Cost Explorer API lives in
# us-east-1 regardless of resource region).

set -euo pipefail

REGION="${AWS_REGION:-ap-northeast-1}"
CE_REGION="us-east-1"

today="$(date +%Y-%m-%d)"
month_start="$(date +%Y-%m-01)"
# End date for get-cost-and-usage is exclusive; use tomorrow.
month_end="$(date -d 'tomorrow' +%Y-%m-%d 2>/dev/null || date -v+1d +%Y-%m-%d)"
forecast_end="$(date -d "$today +30 days" +%Y-%m-%d 2>/dev/null || date -v+30d -j -f %Y-%m-%d "$today" +%Y-%m-%d)"

echo "=== Running EC2 instances in $REGION ==="
aws ec2 describe-instances --region "$REGION" \
    --filters "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name,PublicIpAddress,LaunchTime]' \
    --output table

echo
echo "=== Elastic IPs in $REGION (attached EIP = free; detached = \$0.005/hr) ==="
aws ec2 describe-addresses --region "$REGION" \
    --query 'Addresses[].[PublicIp,InstanceId,AllocationId,AssociationId]' \
    --output table

echo
echo "=== EBS volumes in $REGION ==="
aws ec2 describe-volumes --region "$REGION" \
    --query 'Volumes[].[VolumeId,Size,VolumeType,State,Attachments[0].InstanceId]' \
    --output table

echo
echo "=== Month-to-date cost by service ($month_start → $today) ==="
aws ce get-cost-and-usage --region "$CE_REGION" \
    --time-period "Start=$month_start,End=$month_end" \
    --granularity MONTHLY \
    --metrics UnblendedCost \
    --group-by Type=DIMENSION,Key=SERVICE \
    --query 'ResultsByTime[0].Groups[].[Keys[0],Metrics.UnblendedCost.Amount,Metrics.UnblendedCost.Unit]' \
    --output table \
    || echo "  (Cost Explorer not enabled? Open Billing → Cost Explorer in the console once.)"

echo
echo "=== 30-day forecast ($today → $forecast_end) ==="
aws ce get-cost-forecast --region "$CE_REGION" \
    --time-period "Start=$today,End=$forecast_end" \
    --metric UNBLENDED_COST \
    --granularity MONTHLY \
    --query '[Total.Amount,Total.Unit]' \
    --output text \
    || echo "  (forecast needs ~7 days of data; try again later if empty)"
