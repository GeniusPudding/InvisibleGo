#!/usr/bin/env bash
# Provision InvisibleGo's VM on AWS EC2.
#
# Run from your LOCAL machine (not the VM) after `aws configure`.
# Creates (or reuses if they already exist):
#   - SSH key pair (saved locally as ~/InvisibleGoKey.pem)
#   - Security group (SSH from your current IP, HTTP/HTTPS public)
#   - t3.micro Ubuntu 24.04 instance in Tokyo region
#   - Elastic IP associated with the instance
#
# Prints the SSH command at the end. Idempotent — safe to re-run; it
# detects existing resources by name and skips creation.

set -euo pipefail

REGION="ap-northeast-1"
KEY_NAME="InvisibleGoKey"
SG_NAME="invisiblego-sg"
INSTANCE_NAME="invisiblego"
INSTANCE_TYPE="t3.micro"
KEY_FILE="$HOME/${KEY_NAME}.pem"

echo "==> Checking AWS credentials"
aws sts get-caller-identity --query 'Arn' --output text

# --- Key pair -------------------------------------------------------
if aws ec2 describe-key-pairs --key-names "$KEY_NAME" --region "$REGION" >/dev/null 2>&1; then
    echo "==> Key pair '$KEY_NAME' already exists in AWS"
    if [ ! -f "$KEY_FILE" ]; then
        echo "!! $KEY_FILE missing locally and AWS can't give the private key twice."
        echo "   Options:"
        echo "     A) Copy the .pem from the machine that originally created it."
        echo "     B) Delete the key pair in AWS and re-run:"
        echo "        aws ec2 delete-key-pair --key-name $KEY_NAME --region $REGION"
        exit 1
    fi
else
    echo "==> Creating key pair '$KEY_NAME'"
    aws ec2 create-key-pair \
        --key-name "$KEY_NAME" \
        --query 'KeyMaterial' \
        --output text \
        --region "$REGION" > "$KEY_FILE"
    chmod 400 "$KEY_FILE" 2>/dev/null || true
    echo "   Private key saved to $KEY_FILE (keep this file safe)"
fi

# --- Security group -------------------------------------------------
MY_IP=$(curl -s https://checkip.amazonaws.com | tr -d '\r\n')
echo "==> Your public IP: $MY_IP"

if SG_ID=$(aws ec2 describe-security-groups \
    --group-names "$SG_NAME" \
    --region "$REGION" \
    --query 'SecurityGroups[0].GroupId' \
    --output text 2>/dev/null); then
    echo "==> Security group '$SG_NAME' already exists ($SG_ID)"
else
    echo "==> Creating security group '$SG_NAME'"
    SG_ID=$(aws ec2 create-security-group \
        --group-name "$SG_NAME" \
        --description "InvisibleGo web server" \
        --region "$REGION" \
        --query 'GroupId' \
        --output text)
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 22  --cidr "${MY_IP}/32" --region "$REGION" >/dev/null
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 80  --cidr 0.0.0.0/0     --region "$REGION" >/dev/null
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 443 --cidr 0.0.0.0/0     --region "$REGION" >/dev/null
    echo "   Opened: 22 from $MY_IP, 80 and 443 public"
fi

# --- Latest Ubuntu 24.04 AMI ---------------------------------------
echo "==> Resolving latest Ubuntu 24.04 AMI in $REGION"
AMI_ID=$(aws ec2 describe-images \
    --owners 099720109477 \
    --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" \
              "Name=state,Values=available" \
    --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
    --output text \
    --region "$REGION")
echo "   AMI: $AMI_ID"

# --- Instance -------------------------------------------------------
EXISTING_INSTANCE=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$INSTANCE_NAME" "Name=instance-state-name,Values=pending,running,stopped,stopping" \
    --query 'Reservations[].Instances[0].InstanceId' \
    --output text \
    --region "$REGION" 2>/dev/null || true)

if [ -n "$EXISTING_INSTANCE" ] && [ "$EXISTING_INSTANCE" != "None" ]; then
    INSTANCE_ID="$EXISTING_INSTANCE"
    echo "==> Instance '$INSTANCE_NAME' already exists ($INSTANCE_ID)"
else
    echo "==> Launching $INSTANCE_TYPE Ubuntu 24.04 instance"
    INSTANCE_ID=$(aws ec2 run-instances \
        --image-id "$AMI_ID" \
        --count 1 \
        --instance-type "$INSTANCE_TYPE" \
        --key-name "$KEY_NAME" \
        --security-group-ids "$SG_ID" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
        --region "$REGION" \
        --query 'Instances[0].InstanceId' \
        --output text)
    echo "   Launched: $INSTANCE_ID"
    echo "   Waiting for instance to reach running state..."
    aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"
fi

# --- Elastic IP -----------------------------------------------------
EIP=$(aws ec2 describe-addresses \
    --filters "Name=instance-id,Values=$INSTANCE_ID" \
    --query 'Addresses[0].PublicIp' \
    --output text \
    --region "$REGION" 2>/dev/null || echo "None")

if [ -n "$EIP" ] && [ "$EIP" != "None" ]; then
    PUBLIC_IP="$EIP"
    echo "==> Elastic IP already attached: $PUBLIC_IP"
else
    echo "==> Allocating and associating Elastic IP"
    ALLOC_ID=$(aws ec2 allocate-address --domain vpc --region "$REGION" --query 'AllocationId' --output text)
    aws ec2 associate-address --instance-id "$INSTANCE_ID" --allocation-id "$ALLOC_ID" --region "$REGION" >/dev/null
    PUBLIC_IP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC_ID" --query 'Addresses[0].PublicIp' --output text --region "$REGION")
    echo "   IP: $PUBLIC_IP"
fi

cat <<EOF

=====================================================================
 Provisioning complete.
=====================================================================

 Instance:   $INSTANCE_ID  ($INSTANCE_TYPE, Ubuntu 24.04, $REGION)
 Public IP:  $PUBLIC_IP    (Elastic — won't change on reboot)
 SSH key:    $KEY_FILE

 Next — SSH in and install the app:

   ssh -i $KEY_FILE ubuntu@$PUBLIC_IP
   # inside the VM:
   git clone https://github.com/GeniusPudding/InvisibleGo.git
   cd InvisibleGo
   sudo bash deploy/setup-docker.sh
   # then edit deploy/Caddyfile to set your domain and:
   #   docker compose restart caddy

 Tear down later (stops billing):
   aws ec2 terminate-instances --instance-ids $INSTANCE_ID --region $REGION
   aws ec2 release-address --allocation-id \$(aws ec2 describe-addresses --filters "Name=public-ip,Values=$PUBLIC_IP" --query 'Addresses[0].AllocationId' --output text --region $REGION) --region $REGION

EOF
