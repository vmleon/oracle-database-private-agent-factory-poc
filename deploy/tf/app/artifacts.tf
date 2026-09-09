data "archive_file" "artifact" {
  for_each         = local.artifacts
  type             = "zip"
  source_dir       = each.value.source_dir
  output_file_mode = "0666"
  output_path      = "${path.module}/generated/${each.key}.zip"
}

# Terraform-managed objects rather than a CLI upload: they stay in state, so
# `destroy` empties the bucket before removing it instead of failing on a
# non-empty bucket, and the archive's hash rides in object metadata so a
# changed artifact updates on the next apply.
resource "oci_objectstorage_object" "artifact" {
  for_each  = local.artifacts
  bucket    = oci_objectstorage_bucket.artifacts.name
  namespace = data.oci_objectstorage_namespace.ns.namespace
  object    = "${each.key}.zip"
  source    = data.archive_file.artifact[each.key].output_path

  metadata = {
    content_hash = data.archive_file.artifact[each.key].output_md5
  }
}

# A read-only PAR is how an instance with no credentials fetches its payload.
resource "oci_objectstorage_preauthrequest" "artifact" {
  for_each     = local.artifacts
  namespace    = data.oci_objectstorage_namespace.ns.namespace
  bucket       = oci_objectstorage_bucket.artifacts.name
  name         = "${each.key}_par"
  access_type  = "ObjectRead"
  object_name  = oci_objectstorage_object.artifact[each.key].object
  time_expires = timeadd(time_static.deploy_time.rfc3339, "${var.artifacts_par_expiration_in_days * 24}h")
}

# The PAF kit tarball is orders of magnitude larger than a role artifact and is
# already an archive, so it is uploaded as-is rather than zipped again.
resource "oci_objectstorage_object" "paf_tarball" {
  bucket    = oci_objectstorage_bucket.artifacts.name
  namespace = data.oci_objectstorage_namespace.ns.namespace
  object    = "paf-kit.tar.gz"
  source    = var.paf_tarball_path

  metadata = {
    content_hash = filemd5(var.paf_tarball_path)
  }
}

resource "oci_objectstorage_preauthrequest" "paf_tarball" {
  namespace    = data.oci_objectstorage_namespace.ns.namespace
  bucket       = oci_objectstorage_bucket.artifacts.name
  name         = "paf_tarball_par"
  access_type  = "ObjectRead"
  object_name  = oci_objectstorage_object.paf_tarball.object
  time_expires = timeadd(time_static.deploy_time.rfc3339, "${var.artifacts_par_expiration_in_days * 24}h")
}
