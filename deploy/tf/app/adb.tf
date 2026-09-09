# ADB reachable only from inside the VCN: the workload computes connect over
# the private endpoint, and the ops compute runs Liquibase against it.
resource "oci_database_autonomous_database" "adb" {
  compartment_id = var.compartment_ocid
  db_name        = var.db_name
  display_name   = "${var.label}-adb"
  db_version     = var.db_version
  db_workload    = "OLTP"

  compute_model            = "ECPU"
  compute_count            = var.db_ecpu_count
  data_storage_size_in_tbs = var.db_storage_tbs
  license_model            = "LICENSE_INCLUDED"
  is_auto_scaling_enabled  = false

  admin_password = var.db_admin_password

  subnet_id              = oci_core_subnet.private.id
  private_endpoint_label = "adb"
  nsg_ids                = [oci_core_network_security_group.adb.id]
}

resource "oci_core_network_security_group" "adb" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.label}-nsg-adb"
}

resource "oci_core_network_security_group_security_rule" "adb_sqlnet" {
  network_security_group_id = oci_core_network_security_group.adb.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = var.vcn_cidr
  source_type               = "CIDR_BLOCK"

  tcp_options {
    destination_port_range {
      min = 1522
      max = 1522
    }
  }
}

# The wallet the PAF install wizard and the JDBC clients consume.
resource "oci_database_autonomous_database_wallet" "adb" {
  autonomous_database_id = oci_database_autonomous_database.adb.id
  password               = var.wallet_password
  generate_type          = "SINGLE"
  base64_encode_content  = true
}

resource "local_file" "adb_wallet" {
  filename       = "${path.module}/generated/adb-wallet.zip"
  content_base64 = oci_database_autonomous_database_wallet.adb.content
}

# The ops and paf tiers boot without credentials, so the wallet reaches them
# the same way their playbooks do — as a bucket object behind a read-only PAR.
resource "oci_objectstorage_object" "wallet" {
  bucket    = oci_objectstorage_bucket.artifacts.name
  namespace = data.oci_objectstorage_namespace.ns.namespace
  object    = "adb-wallet.zip"
  source    = local_file.adb_wallet.filename

  metadata = {
    content_hash = local_file.adb_wallet.content_base64sha256
  }
}

resource "oci_objectstorage_preauthrequest" "wallet" {
  namespace    = data.oci_objectstorage_namespace.ns.namespace
  bucket       = oci_objectstorage_bucket.artifacts.name
  name         = "adb_wallet_par"
  access_type  = "ObjectRead"
  object_name  = oci_objectstorage_object.wallet.object
  time_expires = timeadd(time_static.deploy_time.rfc3339, "${var.artifacts_par_expiration_in_days * 24}h")
}
