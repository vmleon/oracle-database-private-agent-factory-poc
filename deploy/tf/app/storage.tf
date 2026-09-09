data "oci_objectstorage_namespace" "ns" {
  compartment_id = var.compartment_ocid
}

# Pins the PAR expiry to apply time. Without a stable timestamp every plan
# would show a diff, because `timestamp()` changes on every evaluation.
resource "time_static" "deploy_time" {}

resource "oci_objectstorage_bucket" "artifacts" {
  compartment_id = var.compartment_ocid
  namespace      = data.oci_objectstorage_namespace.ns.namespace
  name           = "artifacts-${local.project_name}-${local.deploy_id}"
  access_type    = "NoPublicAccess"
}
