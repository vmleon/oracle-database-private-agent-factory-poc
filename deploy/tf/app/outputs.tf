output "lb_ip" {
  description = "Public address of the stack. Served over HTTPS with a self-signed certificate, so a browser warns on first visit."
  value       = oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address
}

output "urls" {
  description = "Entry points served by the load balancer."
  value = {
    customer   = "https://${oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address}/"
    backoffice = "https://${oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address}/backoffice"
    api        = "https://${oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address}/v1"
    paf        = "https://${oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address}/agentFactory"
  }
}

output "ops_public_ip" {
  description = "Bastion address — runs Liquibase against ADB."
  value       = module.ops.public_ip
}

output "adb_ocid" {
  value = oci_database_autonomous_database.adb.id
}

output "adb_wallet_path" {
  description = "Wallet zip for the PAF install wizard and the JDBC clients."
  value       = local_file.adb_wallet.filename
}

output "artifacts_bucket" {
  description = "Bucket holding the per-tier payloads and the ADB wallet."
  value       = oci_objectstorage_bucket.artifacts.name
}

output "genai_endpoint" {
  description = "OCI Generative AI inference endpoint PAF's LLM Management points at."
  value       = local.genai_endpoint
}

output "mcp_server_urls" {
  description = "MCP server URLs to register in PAF, one per wrapper."
  value = {
    for name, port in local.mcp_ports :
    # No trailing slash: with it the wrapper answers 307 to the slashless form,
    # and there is no reason to make PAF follow a redirect on every call.
    name => "https://${oci_load_balancer_load_balancer.internal.ip_address_details[0].ip_address}:${port}/mcp"
  }
}

output "mcp_ca_path" {
  description = "Certificate PAF must trust before any MCP server will connect."
  value       = local_file.mcp_ca.filename
}
