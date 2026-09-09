data "oci_identity_availability_domains" "this" {
  compartment_id = var.compartment_ocid
}

locals {
  # Every tier's playbook receives the same base parameters; each module call
  # adds what only that tier needs.
  common_params = {
    project_name = local.project_name
    region_name  = var.region
  }

  db_params = {
    adb_service        = "${var.db_name}_high"
    adb_admin_user     = "ADMIN"
    adb_admin_password = var.db_admin_password
    adb_wallet_par_url = "${local.object_storage_host}${oci_objectstorage_preauthrequest.wallet.access_uri}"
    wallet_password    = var.wallet_password
  }
}

# ops — bastion, and the host that applies the Liquibase changelog to ADB.
module "ops" {
  source = "../modules/tier"

  compartment_ocid    = var.compartment_ocid
  tier_name           = "ops"
  service_name        = local.project_name
  project_name        = local.project_name
  deploy_id           = local.deploy_id
  region              = var.region
  ads                 = data.oci_identity_availability_domains.this.availability_domains
  subnet_id           = oci_core_subnet.public.id
  assign_public_ip    = true
  ssh_public_key      = var.ssh_public_key
  instance_shape      = var.compute_shape
  instance_ocpus      = 1
  instance_memory_gbs = 8
  artifact_par_url    = "${local.object_storage_host}${oci_objectstorage_preauthrequest.artifact["ansible_ops"].access_uri}"

  ansible_params = merge(local.common_params, local.db_params)
}

# frontend — nginx serving both UI bundles.
module "frontend" {
  source = "../modules/tier"

  compartment_ocid    = var.compartment_ocid
  tier_name           = "frontend"
  service_name        = local.project_name
  project_name        = local.project_name
  deploy_id           = local.deploy_id
  region              = var.region
  ads                 = data.oci_identity_availability_domains.this.availability_domains
  subnet_id           = oci_core_subnet.private.id
  ssh_public_key      = var.ssh_public_key
  instance_shape      = var.compute_shape
  instance_ocpus      = var.compute_ocpus
  instance_memory_gbs = var.compute_memory_gbs
  artifact_par_url    = "${local.object_storage_host}${oci_objectstorage_preauthrequest.artifact["ansible_frontend"].access_uri}"

  ansible_params = merge(local.common_params, {
    backend_host = local.backend_host
  })
}

# backend — Spring Boot, OPA and the company registry API.
module "backend" {
  source = "../modules/tier"

  compartment_ocid    = var.compartment_ocid
  tier_name           = "backend"
  service_name        = local.project_name
  project_name        = local.project_name
  deploy_id           = local.deploy_id
  region              = var.region
  ads                 = data.oci_identity_availability_domains.this.availability_domains
  subnet_id           = oci_core_subnet.private.id
  ssh_public_key      = var.ssh_public_key
  instance_shape      = var.compute_shape
  instance_ocpus      = var.compute_ocpus
  instance_memory_gbs = var.compute_memory_gbs
  artifact_par_url    = "${local.object_storage_host}${oci_objectstorage_preauthrequest.artifact["ansible_backend"].access_uri}"

  ansible_params = merge(local.common_params, local.db_params, {
    paf_host = local.paf_host
  })
}

# paf — the Private Agent Factory container, pointed at OCI Generative AI.
module "paf" {
  source = "../modules/tier"

  compartment_ocid    = var.compartment_ocid
  tier_name           = "paf"
  service_name        = local.project_name
  project_name        = local.project_name
  deploy_id           = local.deploy_id
  region              = var.region
  ads                 = data.oci_identity_availability_domains.this.availability_domains
  subnet_id           = oci_core_subnet.private.id
  ssh_public_key      = var.ssh_public_key
  instance_shape      = var.compute_shape
  instance_ocpus      = 4
  instance_memory_gbs = 32
  artifact_par_url    = "${local.object_storage_host}${oci_objectstorage_preauthrequest.artifact["ansible_paf"].access_uri}"

  ansible_params = merge(local.common_params, local.db_params, {
    backend_host        = local.backend_host
    genai_endpoint      = local.genai_endpoint
    genai_region        = var.genai_region
    paf_tarball_par_url = "${local.object_storage_host}${oci_objectstorage_preauthrequest.paf_tarball.access_uri}"
  })
}
