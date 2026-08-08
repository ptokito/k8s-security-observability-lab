terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

# Latest Ubuntu 22.04 image, looked up dynamically so it never goes stale
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical's official AWS account
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
}

resource "aws_key_pair" "lab" {
  key_name   = "k3s-lab-key"
  public_key = file("~/.ssh/k3s-lab.pub")
}

# Firewall: only your IP can reach SSH (22) and the Kubernetes API (6443)
resource "aws_security_group" "k3s" {
  name        = "k3s-lab-sg"
  description = "k3s lab - locked to my IP"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  ingress {
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Spot EC2 instance that installs k3s at boot with audit logging on
resource "aws_instance" "k3s" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.lab.key_name
  vpc_security_group_ids = [aws_security_group.k3s.id]

  instance_market_options {
    market_type = "spot"
    spot_options {
      spot_instance_type             = "one-time"
      instance_interruption_behavior = "terminate"
    }
  }

  user_data = <<-USERDATA
    #!/bin/bash
    # Write the audit policy BEFORE k3s starts, so logging is on from boot
    mkdir -p /var/lib/rancher/k3s/server
    cat > /var/lib/rancher/k3s/server/audit-policy.yaml << 'POLICY'
    apiVersion: audit.k8s.io/v1
    kind: Policy
    rules:
      - level: Metadata
        resources:
          - group: ""
            resources: ["secrets", "configmaps", "serviceaccounts"]
      - level: RequestResponse
        resources:
          - group: "rbac.authorization.k8s.io"
      - level: Metadata
    POLICY

    # Install k3s with the audit log wired into the API server
    curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
      --kube-apiserver-arg=audit-log-path=/var/lib/rancher/k3s/server/logs/audit.log \
      --kube-apiserver-arg=audit-policy-file=/var/lib/rancher/k3s/server/audit-policy.yaml \
      --kube-apiserver-arg=audit-log-maxage=1" sh -
  USERDATA

  tags = {
    Name    = "k3s-security-lab"
    Project = "k8s-security-observability-lab"
  }
}
