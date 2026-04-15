output "alb_dns_name" {
  description = "ALB DNS name — add as CNAME for api.customer-analyticsgo.trade in Cloudflare"
  value       = aws_lb.main.dns_name
}

output "acm_validation_cname_name" {
  description = "Add this as CNAME name in Cloudflare to validate the ACM certificate"
  value       = tolist(aws_acm_certificate.main.domain_validation_options)[0].resource_record_name
}

output "acm_validation_cname_value" {
  description = "Add this as CNAME target in Cloudflare to validate the ACM certificate"
  value       = tolist(aws_acm_certificate.main.domain_validation_options)[0].resource_record_value
}

output "ecr_repository_url" {
  description = "ECR URL — use this to push your Docker image"
  value       = aws_ecr_repository.backend.repository_url
}

output "rds_endpoint" {
  description = "RDS endpoint — for DB connection debugging"
  value       = aws_db_instance.main.endpoint
  sensitive   = true
}

output "redis_endpoint" {
  description = "Redis endpoint"
  value       = aws_elasticache_cluster.main.cache_nodes[0].address
  sensitive   = true
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}
