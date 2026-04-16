# DNS is managed in Cloudflare — not in Route 53.
#
# After terraform apply, do these two steps manually in Cloudflare:
#
# Step 1 — Validate the ACM certificate:
#   Run: terraform output -raw acm_validation_cname_name
#         terraform output -raw acm_validation_cname_value
#   In Cloudflare: DNS → Add record → CNAME
#     Name:    <acm_validation_cname_name>
#     Target:  <acm_validation_cname_value>
#     Proxy:   OFF (grey cloud — must be DNS only)
#
# Step 2 — Point api subdomain to the ALB:
#   Run: terraform output alb_dns_name
#   In Cloudflare: DNS → Add record → CNAME
#     Name:    api
#     Target:  <alb_dns_name>
#     Proxy:   OFF (grey cloud — ALB handles HTTPS itself)
