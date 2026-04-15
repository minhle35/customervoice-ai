terraform {
  backend "s3" {
    bucket         = "customervoice-ai-tf-state-1776227497"
    key            = "prod/terraform.tfstate"
    region         = "ap-southeast-2"
    encrypt        = true
    dynamodb_table = "terraform-lock"
  }
}