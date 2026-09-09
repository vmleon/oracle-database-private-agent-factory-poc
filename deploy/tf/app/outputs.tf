output "lb_ip" {
  description = "Public address of the stack."
  value       = oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address
}

output "urls" {
  description = "Entry points served by the load balancer."
  value = {
    customer   = "http://${oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address}/mobile"
    backoffice = "http://${oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address}/backoffice"
    api        = "http://${oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address}/api"
    paf        = "http://${oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address}/agentFactory"
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
