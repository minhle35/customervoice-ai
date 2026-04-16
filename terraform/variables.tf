variable "aws_region" {
  default = "ap-southeast-2"
}

variable "app_name" {
  default = "customervoice-ai"
}

variable "db_password" {
  description = "RDS master password — set via: export TF_VAR_db_password=yourpassword"
  sensitive   = true
}

variable "backend_image_tag" {
  description = "ECR image tag to deploy — defaults to latest"
  default     = "latest"
}
