locals {
  cloud_init_content = templatefile("${path.module}/userdata/bootstrap.tftpl", {
    service_name        = var.service_name
    tier_name           = var.tier_name
    region_name         = var.region
    artifact_par_url    = var.artifact_par_url
    ansible_params_json = jsonencode(var.ansible_params)
  })
}

# Filtering to a numbered Oracle Linux 9 release keeps a plan from being
# perturbed by unrelated marketplace images sorting first.
data "oci_core_images" "ol9" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Oracle Linux"
  operating_system_version = "9"
  shape                    = var.instance_shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"

  filter {
    name   = "display_name"
    values = ["^Oracle-Linux-9\\.\\d+-\\d{4}\\.\\d{2}\\.\\d{2}-\\d+$"]
    regex  = true
  }
}

resource "oci_core_instance" "this" {
  availability_domain = lookup(var.ads[0], "name")
  compartment_id      = var.compartment_ocid
  display_name        = "${var.tier_name}-${var.project_name}-${var.deploy_id}"
  shape               = var.instance_shape

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data           = base64encode(local.cloud_init_content)
  }

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_gbs
  }

  source_details {
    source_type = "image"
    source_id   = data.oci_core_images.ol9.images[0].id
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

  create_vnic_details {
    subnet_id        = var.subnet_id
    assign_public_ip = var.assign_public_ip
    hostname_label   = var.tier_name
  }
}
