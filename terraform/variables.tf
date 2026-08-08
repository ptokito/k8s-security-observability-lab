variable "my_ip" {
  description = "Your public IP in CIDR form, e.g. 1.2.3.4/32"
  type        = string
}

variable "instance_type" {
  description = "Spot instance size"
  type        = string
  default     = "t3a.medium"
}
