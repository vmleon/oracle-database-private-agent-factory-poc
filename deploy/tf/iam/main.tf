# The paf compute calls Generative AI as an instance principal, so PAF's LLM
# and embedding connections carry no key material at all.
resource "oci_identity_dynamic_group" "compute" {
  compartment_id = var.tenancy_ocid
  name           = "${var.label}-compute-dg"
  description    = "Compute instances in the ${var.label} compartment"
  matching_rule  = "ALL {instance.compartment.id = '${var.compartment_ocid}'}"
}

# The Select AI profiles authenticate as OCI$RESOURCE_PRINCIPAL, which resolves
# to the Autonomous Database instance itself.
resource "oci_identity_dynamic_group" "adb" {
  compartment_id = var.tenancy_ocid
  name           = "${var.label}-adb-dg"
  description    = "Autonomous Databases in the ${var.label} compartment"
  matching_rule  = "ALL {resource.type = 'autonomousdatabase', resource.compartment.id = '${var.compartment_ocid}'}"
}

data "oci_identity_compartment" "workload" {
  id = var.compartment_ocid
}

resource "oci_identity_policy" "genai" {
  compartment_id = var.tenancy_ocid
  name           = "${var.label}-genai-policy"
  description    = "Lets the ${var.label} compute and database call Generative AI"

  statements = [
    "allow dynamic-group ${oci_identity_dynamic_group.compute.name} to use generative-ai-family in compartment ${data.oci_identity_compartment.workload.name}",
    "allow dynamic-group ${oci_identity_dynamic_group.adb.name} to use generative-ai-family in compartment ${data.oci_identity_compartment.workload.name}",
  ]
}
