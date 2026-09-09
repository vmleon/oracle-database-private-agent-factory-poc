output "compute_dynamic_group" {
  description = "Dynamic group the paf compute authenticates through."
  value       = oci_identity_dynamic_group.compute.name
}

output "adb_dynamic_group" {
  description = "Dynamic group the Autonomous Database authenticates through."
  value       = oci_identity_dynamic_group.adb.name
}

output "policy" {
  value = oci_identity_policy.genai.name
}
