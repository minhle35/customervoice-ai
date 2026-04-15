resource "aws_secretsmanager_secret" "app" {
  name        = "${var.app_name}/production"
  description = "App secrets for CustomerVoice AI — managed by Terraform"

  tags = { Name = "${var.app_name}-secrets" }
}

# Placeholder values — update with real keys after apply:
#   aws secretsmanager put-secret-value \
#     --secret-id customervoice-ai/production \
#     --secret-string '{"OPENROUTER_API_KEY":"sk-or-...","GOOGLE_REVIEWS_API_KEY":"...","SECRET_KEY":"..."}'
resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DB__PASSWORD           = var.db_password
    OPENROUTER_API_KEY     = "REPLACE_ME"
    GOOGLE_REVIEWS_API_KEY = "REPLACE_ME"
    SECRET_KEY             = "REPLACE_ME"
  })

  # Ignore changes after first apply — you update secrets via CLI, not Terraform
  lifecycle {
    ignore_changes = [secret_string]
  }
}
