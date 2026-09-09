resource "random_string" "deploy_id" {
  length  = 6
  special = false
  upper   = false
}

locals {
  project_name = var.label
  deploy_id    = random_string.deploy_id.result

  genai_endpoint = "https://inference.generativeai.${var.genai_region}.oci.oraclecloud.com"

  object_storage_host = "https://objectstorage.${var.region}.oraclecloud.com"

  # Artifact name -> the directory zipped and published for it. Each entry
  # produces an archive, a bucket object, and a read-only PAR, so adding a
  # tier's payload is one line here rather than three resource blocks.
  artifacts = {
    ansible_ops      = { source_dir = "${path.module}/../../ansible/ops" }
    ansible_frontend = { source_dir = "${path.module}/../../ansible/frontend" }
    ansible_backend  = { source_dir = "${path.module}/../../ansible/backend" }
    ansible_paf      = { source_dir = "${path.module}/../../ansible/paf" }
  }
}

# Tiers address each other by their VCN private-DNS names rather than by
# module outputs: backend and paf each need the other's address, which as
# module references would be a dependency cycle.
locals {
  private_domain = "${oci_core_subnet.private.dns_label}.${oci_core_vcn.main.dns_label}.oraclevcn.com"

  frontend_host = "frontend.${local.private_domain}"
  backend_host  = "backend.${local.private_domain}"
  paf_host      = "paf.${local.private_domain}"
}
